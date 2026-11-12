from ultralytics import YOLO
import os
import uuid
import sqlite3
import base64
import cv2
import numpy as np
import secrets
import hashlib
from cryptography.fernet import Fernet
import threading
import time

from datetime import datetime
from functools import wraps
import os


from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, session, redirect, url_for
)

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from ultralytics import YOLO

# Secure RTSP encryption
RTSP_ENCRYPTION_KEY = os.environ.get("RTSP_ENCRYPTION_KEY")

if not RTSP_ENCRYPTION_KEY:
    raise RuntimeError("RTSP_ENCRYPTION_KEY is not configured.")

rtsp_cipher = Fernet(RTSP_ENCRYPTION_KEY.encode())

# ======================================
# FLASK CONFIGURATION
# ======================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="statics",
    static_url_path="/statics"
)

app.secret_key = os.environ.get(
    "CROWDSENSE_SECRET_KEY",
    "change-this-secret-before-deployment"
)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DATABASE = os.path.join(BASE_DIR, "crowdsense.db")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ======================================
# DATABASE CONNECTION
# ======================================


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():

    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner',
            location_name TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            location_name TEXT NOT NULL,
            address TEXT NOT NULL,
            is_public INTEGER DEFAULT 1,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT NOT NULL,
            person_count INTEGER NOT NULL,
            density TEXT NOT NULL,
            result_image TEXT,
            created_at TEXT NOT NULL,
            owner_id INTEGER,
            location_id INTEGER
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS live_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_count INTEGER NOT NULL,
            density TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            owner_id INTEGER,
            location_id INTEGER
        )
    """)

    # Safely migrate existing databases.
    for table in ("detections", "live_alerts"):

        columns = [
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        ]

        if "owner_id" not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER"
            )

        if "location_id" not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN location_id INTEGER"
            )

    # Improve location-specific lookup performance.
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_detections_location
        ON detections(location_id, created_at)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_alerts_location
        ON live_alerts(location_id, created_at)
    """)


    connection.execute("""
        CREATE TABLE IF NOT EXISTS location_status (
            location_id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            person_count INTEGER NOT NULL,
            density TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    connection.execute("""
    CREATE TABLE IF NOT EXISTS crowd_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        person_count INTEGER NOT NULL,
        density TEXT NOT NULL,
        created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
    CREATE INDEX IF NOT EXISTS idx_crowd_history_location
    ON crowd_history (location_id, id)
    """)


    # ACCOUNT SECURITY: safely add email fields to existing users.
    user_columns = [
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    ]

    if "email" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN email TEXT")

    if "email_verified" not in user_columns:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0
        """)

    # Allow each non-empty email address to belong to one account.
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
        ON users(email)
        WHERE email IS NOT NULL AND email != ''
    """)

    # PASSWORD RESET AND EMAIL VERIFICATION TOKENS
    connection.execute("""
        CREATE TABLE IF NOT EXISTS account_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            token_type TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # REGISTERED CAMERAS FOR EACH LOCATION
    connection.execute("""
        CREATE TABLE IF NOT EXISTS camera_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            camera_name TEXT NOT NULL,
            camera_type TEXT NOT NULL
                CHECK(camera_type IN ('ip_cctv', 'usb', 'mobile')),
            token_hash TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            last_seen_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_camera_devices_location
        ON camera_devices(location_id, owner_id)
    """)

    camera_columns = [
        row["name"]
        for row in connection.execute(
        "PRAGMA table_info(camera_devices)"
        ).fetchall()
        ]
    if "encrypted_rtsp_url" not in camera_columns:
        connection.execute("""
        ALTER TABLE camera_devices
        ADD COLUMN encrypted_rtsp_url TEXT
    """)

    connection.commit()
    connection.close()


init_db()



# ======================================
# AUTHENTICATION
# ======================================

def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        if session.get("role") != "admin":
            return "Access denied", 403

        return function(*args, **kwargs)

    return wrapper


# ======================================
# ADMIN SETUP
# ======================================

@app.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():

    connection = get_db()

    existing = connection.execute(
        "SELECT id FROM users WHERE role='admin'"
    ).fetchone()

    if existing:
        connection.close()
        return redirect(url_for("login"))

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or len(password) < 10:
            connection.close()
            return "Username required. Password must be at least 10 characters."

        try:

            connection.execute("""
                INSERT INTO users
                (username, password_hash, role, location_name)
                VALUES (?, ?, 'admin', 'CrowdSense Administration')
            """, (
                username,
                generate_password_hash(password)
            ))

            connection.commit()
            connection.close()

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            connection.close()
            return "Username already exists."

    connection.close()
    return render_template("setup_admin.html")


# ======================================
# LOGIN
# ======================================


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        connection = get_db()

        try:
            user = connection.execute(
                "SELECT * FROM users WHERE username=?",
                (username,)
            ).fetchone()
        finally:
            connection.close()

        if user and check_password_hash(
            user["password_hash"], password
        ):


            session.clear()

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["location_name"] = user["location_name"]

            if user["role"] == "admin":
                return redirect(url_for("admin_users"))

            return redirect(url_for("dashboard"))

        return render_template(
            "login.html",
            error="Invalid username or password."
        )

    return render_template("login.html")



@app.route("/logout")
@login_required
def logout():

    session.clear()
    return redirect(url_for("login"))


# ======================================
# ADMIN: CREATE OWNER ACCOUNTS
# ======================================

@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():

    connection = get_db()

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        location = request.form.get("location_name", "").strip()

        if not username or not location or len(password) < 10:
            connection.close()
            return "Fill all fields. Password must be at least 10 characters."

        try:

            connection.execute("""
                INSERT INTO users
                (username, password_hash, role, location_name)
                VALUES (?, ?, 'owner', ?)
            """, (
                username,
                generate_password_hash(password),
                location
            ))

            connection.commit()

        except sqlite3.IntegrityError:

            connection.close()
            return "Username already exists."

    users = connection.execute("""
        SELECT id, username, location_name
        FROM users
        WHERE role='owner'
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return render_template("admin_users.html", users=users)


@app.route("/admin/reset-owner-password/<int:user_id>", methods=["POST"])
@admin_required
def reset_owner_password(user_id):

    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if len(password) < 10:
        return redirect(url_for(
            "admin_users",
            message="Password must be at least 10 characters."
        ))

    if password != confirm_password:
        return redirect(url_for(
            "admin_users",
            message="Passwords do not match."
        ))

    connection = get_db()

    try:

        owner = connection.execute("""
            SELECT id FROM users
            WHERE id = ? AND role = 'owner'
        """, (user_id,)).fetchone()

        if not owner:
            return redirect(url_for(
                "admin_users",
                message="Owner account not found."
            ))

        connection.execute("""
            UPDATE users
            SET password_hash = ?
            WHERE id = ? AND role = 'owner'
        """, (
            generate_password_hash(password),
            user_id
        ))

        connection.commit()

        return redirect(url_for(
            "admin_users",
            message="Owner password updated successfully."
        ))

    except Exception as error:

        connection.rollback()
        print("Password reset error:", error)

        return redirect(url_for(
            "admin_users",
            message="Could not reset password."
        ))

    finally:
        connection.close()



@app.route("/owner/signup", methods=["GET", "POST"])
def owner_signup():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        location = request.form.get("location_name", "").strip()

        if not username or not email or not location or not password:
            return render_template(
                "owner_signup.html",
                error="Please fill in all fields."
            )

        if "@" not in email or "." not in email.split("@")[-1]:
            return render_template(
                "owner_signup.html",
                error="Please enter a valid email address."
            )

        if len(password) < 10:
            return render_template(
                "owner_signup.html",
                error="Password must be at least 10 characters."
            )

        if password != confirm_password:
            return render_template(
                "owner_signup.html",
                error="Passwords do not match."
            )

        connection = get_db()

        try:
            connection.execute("""
                INSERT INTO users
                (username, email, password_hash, role, location_name)
                VALUES (?, ?, ?, 'owner', ?)
            """, (
                username,
                email,
                generate_password_hash(password),
                location
            ))

            connection.commit()

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            return render_template(
                "owner_signup.html",
                error="Username or email already exists."
            )

        finally:
            connection.close()

    return render_template("owner_signup.html")



# ======================================
# YOLO MODEL
# ======================================


# ======================================
# YOLO MODEL
# ======================================

model = None


def get_model():
    global model

    if model is None:
        print("Loading YOLOv8n model...")

        model_path = os.path.join(BASE_DIR, "yolov8n.pt")

        if os.path.exists(model_path):
            model = YOLO(model_path)
        else:
            print("Model not found locally. Downloading YOLOv8n...")
            model = YOLO("yolov8n.pt")

        print("YOLOv8n loaded successfully!")

    return model




def classify_density(count):

    if count <= 5:
        return "Low"

    if count <= 15:
        return "Moderate"

    return "High"


def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def run_ip_camera(camera_id, owner_id, location_id, camera_name,
                  capture, stop_event):

    failed_reads = 0

    try:
        with app.app_context():

            while not stop_event.is_set():

                success, frame = capture.read()

                if not success or frame is None:
                    failed_reads += 1

                    if failed_reads >= 10:
                        print("IP camera stream lost:", camera_name)
                        break

                    time.sleep(0.5)
                    continue

                failed_reads = 0

                results = get_model().predict(
                    source=frame,
                    imgsz=640,
                    conf=0.20,
                    iou=0.50,
                    max_det=500,
                    classes=[0],
                    device="cpu",
                    verbose=False
                )

                result = results[0]

                person_count = (
                    int((result.boxes.cls == 0).sum().item())
                    if result.boxes is not None else 0
                )

                density = classify_density(person_count)

                current_time = datetime.now()
                timestamp = current_time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                connection = get_db()

                try:
                    connection.execute("""
                        INSERT INTO location_status
                        (location_id, owner_id, person_count, density, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(location_id) DO UPDATE SET
                            owner_id = excluded.owner_id,
                            person_count = excluded.person_count,
                            density = excluded.density,
                            updated_at = excluded.updated_at
                    """, (
                        location_id, owner_id, person_count,
                        density, timestamp
                    ))

                    last_reading = connection.execute("""
                        SELECT created_at FROM crowd_history
                        WHERE location_id = ?
                        ORDER BY id DESC LIMIT 1
                    """, (location_id,)).fetchone()

                    should_save = last_reading is None

                    if last_reading:
                        previous_time = datetime.strptime(
                            last_reading["created_at"],
                            "%Y-%m-%d %H:%M:%S"
                        )

                        should_save = (
                            current_time - previous_time
                        ).total_seconds() >= 15

                    if should_save:
                        connection.execute("""
                            INSERT INTO crowd_history
                            (location_id, owner_id, person_count,
                             density, created_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            location_id, owner_id, person_count,
                            density, timestamp
                        ))

                    connection.execute("""
                        UPDATE camera_devices
                        SET last_seen_at = ?
                        WHERE id = ? AND owner_id = ?
                    """, (timestamp, camera_id, owner_id))

                    alert_key = (owner_id, location_id, camera_id)

                    if density == "High" and not live_alert_active.get(
                        alert_key, False
                    ):
                        connection.execute("""
                            INSERT INTO live_alerts
                            (person_count, density, source, created_at,
                             owner_id, location_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            person_count,
                            density,
                            "IP CCTV: " + camera_name,
                            timestamp,
                            owner_id,
                            location_id
                        ))

                        live_alert_active[alert_key] = True

                    elif density != "High":
                        live_alert_active[alert_key] = False

                    connection.commit()

                finally:
                    connection.close()

                # Limit CPU usage on the laptop.
                stop_event.wait(1.2)

    except Exception as error:
        print("IP camera worker error:", camera_name, error)

    finally:
        capture.release()

        alert_key = (owner_id, location_id, camera_id)
        live_alert_active[alert_key] = False

        with camera_workers_lock:
            camera_workers.pop(camera_id, None)

        print("IP camera worker stopped:", camera_name)


# ======================================
# PUBLIC HOMEPAGE
# ======================================

@app.route("/")
def public_home():

    return render_template("public.html")


@app.route("/mobile-camera")
@login_required
def mobile_camera():

    if session.get("role") != "owner":
        return "Access denied.", 403

    return render_template("mobile_camera.html")


@app.route("/health")
def health():

    return jsonify({
        "status": "success",
        "message": "CrowdSense server is running!"
    })


# ======================================
# PUBLIC LOCATIONS API
# ======================================



@app.route("/api/public-locations")
def public_locations():

    connection = get_db()

    locations = connection.execute("""
        SELECT
            l.id,
            l.location_name,
            l.address,

            COALESCE(
                s.person_count,
                (
                    SELECT d.person_count
                    FROM detections d
                    WHERE d.location_id = l.id
                    ORDER BY d.id DESC
                    LIMIT 1
                ),
                (
                    SELECT a.person_count
                    FROM live_alerts a
                    WHERE a.location_id = l.id
                    ORDER BY a.id DESC
                    LIMIT 1
                )
            ) AS people,

            COALESCE(
                s.density,
                (
                    SELECT d.density
                    FROM detections d
                    WHERE d.location_id = l.id
                    ORDER BY d.id DESC
                    LIMIT 1
                ),
                (
                    SELECT a.density
                    FROM live_alerts a
                    WHERE a.location_id = l.id
                    ORDER BY a.id DESC
                    LIMIT 1
                )
            ) AS density,

            COALESCE(
                s.updated_at,
                (
                    SELECT d.created_at
                    FROM detections d
                    WHERE d.location_id = l.id
                    ORDER BY d.id DESC
                    LIMIT 1
                ),
                (
                    SELECT a.created_at
                    FROM live_alerts a
                    WHERE a.location_id = l.id
                    ORDER BY a.id DESC
                    LIMIT 1
                )
            ) AS updated_at

        FROM locations l

        LEFT JOIN location_status s
        ON s.location_id = l.id

        WHERE l.is_public = 1
        ORDER BY l.location_name

    """).fetchall()

    connection.close()

    return jsonify({
        "success": True,
        "locations": [
            {
                "id": row["id"],
                "location_name": row["location_name"],
                "address": row["address"],
                "people": row["people"],
                "density": row["density"] or "No data",
                "updated_at": row["updated_at"]
            }
            for row in locations
        ]
    })




# ======================================
# OWNER: REGISTER LOCATION
# ======================================

@app.route("/api/owner-locations")
@login_required
def get_owner_locations():

    if session.get("role") != "owner":
        return jsonify({
            "success": False,
            "message": "Owner access required."
        }), 403

    connection = get_db()

    locations = connection.execute("""
        SELECT id, location_name, address, is_public
        FROM locations
        WHERE owner_id = ?
        ORDER BY id DESC
    """, (session["user_id"],)).fetchall()

    connection.close()

    return jsonify({
        "success": True,
        "locations": [
            {
                "id": row["id"],
                "location_name": row["location_name"],
                "address": row["address"],
                "is_public": bool(row["is_public"])
            }
            for row in locations
        ]
    })


@app.route("/owner/add-location", methods=["POST"])
@login_required
def add_location():

    if session.get("role") != "owner":
        return jsonify({
            "success": False,
            "message": "Only location owners can register locations."
        }), 403

    location_name = request.form.get("location_name", "").strip()
    address = request.form.get("address", "").strip()
    is_public = 1 if request.form.get("is_public") == "on" else 0

    if not location_name or not address:
        return jsonify({
            "success": False,
            "message": "Location name and address are required."
        }), 400

    connection = get_db()

    connection.execute("""
        INSERT INTO locations
        (owner_id, location_name, address, is_public)
        VALUES (?, ?, ?, ?)
    """, (
        session["user_id"],
        location_name,
        address,
        is_public
    ))

    connection.commit()
    connection.close()

    return jsonify({
        "success": True,
        "message": "Location registered successfully."
    })


@app.route("/owner/delete-location/<int:location_id>", methods=["POST"])
@login_required
def delete_location(location_id):

    if session.get("role") != "owner":
        return jsonify({
            "success": False,
            "message": "Only location owners can delete locations."
        }), 403

    connection = get_db()

    try:
        # Verify that this location belongs to the logged-in owner
        location = connection.execute("""
            SELECT id FROM locations
            WHERE id = ? AND owner_id = ?
        """, (
            location_id,
            session["user_id"]
        )).fetchone()

        if not location:
            return jsonify({
                "success": False,
                "message": "Location not found or access denied."
            }), 404

        # Delete associated crowd history
        connection.execute("""
            DELETE FROM crowd_history
            WHERE location_id = ? AND owner_id = ?
        """, (
            location_id,
            session["user_id"]
        ))

        # Delete current crowd status
        connection.execute("""
            DELETE FROM location_status
            WHERE location_id = ? AND owner_id = ?
        """, (
            location_id,
            session["user_id"]
        ))

        # Delete the registered location
        connection.execute("""
            DELETE FROM locations
            WHERE id = ? AND owner_id = ?
        """, (
            location_id,
            session["user_id"]
        ))

        connection.commit()

        return jsonify({
            "success": True,
            "message": "Location deleted successfully."
        })

    except Exception as error:
        connection.rollback()
        print("Location deletion error:", error)

        return jsonify({
            "success": False,
            "message": "Could not delete location."
        }), 500

    finally:
        connection.close()

# ======================================
# OWNER DASHBOARD
# ======================================

# Both endpoint names are supported:
# url_for("dashboard") and url_for("home")

@app.route("/dashboard", endpoint="home")
@app.route("/dashboard")
@login_required
def dashboard():

    return render_template(
        "index.html",
        active_page="dashboard"
    )


@app.route("/monitoring")
@login_required
def monitoring():

    return render_template(
        "monitoring.html",
        active_page="monitoring"
    )


@app.route("/detection")
@login_required
def detection():

    return render_template(
        "detection.html",
        active_page="detection"
    )


@app.route("/analytics")
@login_required
def analytics():

    return render_template(
        "analytics.html",
        active_page="analytics"
    )


@app.route("/alerts")
@login_required
def alerts():

    return render_template(
        "alerts.html",
        active_page="alerts"
    )


@app.route("/locations")
@login_required
def locations():

    return render_template(
        "locations.html",
        active_page="locations"
    )


@app.route("/settings")
@login_required
def settings():

    return render_template(
        "settings.html",
        active_page="settings"
    )


# ======================================
# IMAGE UPLOAD
# ======================================

@app.route("/upload", methods=["POST"])
@login_required
def upload_image():

    if "image" not in request.files:

        return jsonify({
            "success": False,
            "message": "No image received."
        }), 400

    file = request.files["image"]

    if file.filename == "" or not allowed_file(file.filename):

        return jsonify({
            "success": False,
            "message": "Invalid image."
        }), 400

    original_name = secure_filename(file.filename)
    extension = original_name.rsplit(".", 1)[1].lower()

    unique_filename = f"{uuid.uuid4().hex}.{extension}"

    file.save(
        os.path.join(UPLOAD_FOLDER, unique_filename)
    )

    return jsonify({
        "success": True,
        "filename": unique_filename,
        "image_url": f"/uploads/{unique_filename}"
    })


@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename
    )


@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "success": False,
        "message": "Maximum upload size is 8 MB."
    }), 413


# ======================================
# IMAGE DETECTION
# ======================================



@app.route("/detect", methods=["POST"])
@login_required
def detect():
    import os
    import cv2
    from datetime import datetime
    from flask import request, jsonify, session
    from werkzeug.utils import secure_filename

    owner_id = session["user_id"]

    # Check uploaded image
    if "image" not in request.files:
        return jsonify({
            "success": False,
            "message": "No image uploaded."
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "success": False,
            "message": "Please select an image."
        }), 400

    # Get the selected location
    location_id = request.form.get("location_id", type=int)

    connection = get_db()

    # If no location is selected, automatically use the
    # owner's location only when they have exactly one.
    if not location_id:
        locations = connection.execute(
            "SELECT id FROM locations WHERE owner_id = ?",
            (owner_id,)
        ).fetchall()

        if len(locations) == 1:
            location_id = locations[0]["id"]
        elif len(locations) == 0:
            connection.close()
            return jsonify({
                "success": False,
                "message": "Register a location before detecting."
            }), 400
        else:
            connection.close()
            return jsonify({
                "success": False,
                "message": "Please select a location."
            }), 400

    # Verify that this location belongs to the logged-in owner
    location = connection.execute(
        """
        SELECT id FROM locations
        WHERE id = ? AND owner_id = ?
        """,
        (location_id, owner_id)
    ).fetchone()

    if not location:
        connection.close()
        return jsonify({
            "success": False,
            "message": "Invalid location selected."
        }), 403

    # Save uploaded image
    filename = secure_filename(file.filename)
    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{filename}"

    upload_folder = app.config["UPLOAD_FOLDER"]

    os.makedirs(upload_folder, exist_ok=True)

    image_path = os.path.join(upload_folder, unique_filename)
    file.save(image_path)

    # Read image
    image = cv2.imread(image_path)

    if image is None:
        connection.close()
        return jsonify({
            "success": False,
            "message": "Could not read uploaded image."
        }), 400

    try:
        # Run YOLO person detection
        results = get_model().predict(
            source=image,
            classes=[0],
            imgsz=640,
            conf=0.2,
            device="cpu",
            verbose=False
        )

        person_count = len(results[0].boxes)

        # Determine crowd density
        if person_count < 10:
            density = "Low"
        elif person_count < 25:
            density = "Medium"
        else:
            density = "High"

        # Save annotated image
        annotated_image = results[0].plot()

        result_filename = "result_" + unique_filename
        result_path = os.path.join(upload_folder, result_filename)

        cv2.imwrite(result_path, annotated_image)

        # Save detection with owner and location IDs
        connection.execute(
            """
            INSERT INTO detections
            (
                image_name,
                person_count,
                density,
                result_image,
                created_at,
                owner_id,
                location_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unique_filename,
                person_count,
                density,
                result_filename,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                owner_id,
                location_id
            )
        )

        connection.commit()

        return jsonify({
            "success": True,
            "person_count": person_count,
            "density": density,
            "location_id": location_id,
            "image": f"/uploads/{result_filename}",
            "message": "Detection completed successfully."
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:
        connection.close()


# ======================================
# OWNER ANALYTICS
# ======================================

@app.route("/api/analytics")
@login_required
def get_analytics():

    owner_id = session["user_id"]

    connection = get_db()

    total = connection.execute(
        "SELECT COUNT(*) AS total FROM detections WHERE owner_id=?",
        (owner_id,)
    ).fetchone()["total"]

    average = connection.execute(
        "SELECT AVG(person_count) AS average FROM detections WHERE owner_id=?",
        (owner_id,)
    ).fetchone()["average"]

    highest = connection.execute(
        "SELECT MAX(person_count) AS highest FROM detections WHERE owner_id=?",
        (owner_id,)
    ).fetchone()["highest"]

    history = connection.execute("""
        SELECT *
        FROM detections
        WHERE owner_id=?
        ORDER BY id DESC
        LIMIT 20
    """, (owner_id,)).fetchall()

    density = connection.execute("""
        SELECT density, COUNT(*) AS total
        FROM detections
        WHERE owner_id=?
        GROUP BY density
    """, (owner_id,)).fetchall()

    connection.close()

    return jsonify({
        "total_detections": total,
        "average_people": round(average or 0, 2),
        "highest_people": highest or 0,
        "density_distribution": [
            dict(row) for row in density
        ],
        "history": [
            dict(row) for row in history
        ]
    })


# ======================================
# OWNER ALERTS
# ======================================

@app.route("/api/alerts")
@login_required
def get_alerts():

    owner_id = session["user_id"]

    connection = get_db()

    alerts = connection.execute("""
        SELECT
            id,
            image_name,
            person_count,
            density,
            created_at,
            'Image Detection' AS source_type
        FROM detections
        WHERE density='High' AND owner_id=?

        UNION ALL

        SELECT
            id,
            source AS image_name,
            person_count,
            density,
            created_at,
            'Live Camera' AS source_type
        FROM live_alerts
        WHERE density='High' AND owner_id=?

        ORDER BY created_at DESC
        LIMIT 50
    """, (owner_id, owner_id)).fetchall()

    connection.close()

    return jsonify({
        "total_alerts": len(alerts),
        "alerts": [
            dict(row) for row in alerts
        ]
    })


# ======================================
# OWNER LIVE CAMERA
# ======================================

live_alert_active = {}
latest_live_status = {}
# IP CCTV camera workers
camera_workers = {}
camera_workers_lock = threading.Lock()


@app.route("/live-detect", methods=["POST"])
@login_required
def live_detect():

    owner_id = session["user_id"]

    try:

        frame_file = request.files.get("frame")

        if frame_file is None:
            return jsonify({
                "success": False,
                "message": "No frame received."
            }), 400

        # Get and validate the selected location.
        location_id = request.form.get("location_id")

        connection = get_db()

        if location_id:
            try:
                location_id = int(location_id)
            except (ValueError, TypeError):
                connection.close()
                return jsonify({
                    "success": False,
                    "message": "Invalid location selected."
                }), 400

            location = connection.execute("""
                SELECT id FROM locations
                WHERE id = ? AND owner_id = ?
            """, (location_id, owner_id)).fetchone()

        else:
            locations = connection.execute("""
                SELECT id FROM locations
                WHERE owner_id = ?
            """, (owner_id,)).fetchall()

            if len(locations) == 1:
                location_id = locations[0]["id"]
                location = locations[0]
            else:
                connection.close()
                return jsonify({
                    "success": False,
                    "message": "Please select a location before starting live detection."
                }), 400

        if not location:
            connection.close()
            return jsonify({
                "success": False,
                "message": "Location not found or access denied."
            }), 403

        connection.close()

        image_bytes = np.frombuffer(
            frame_file.read(),
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            image_bytes,
            cv2.IMREAD_COLOR
        )

        if frame is None:
            return jsonify({
                "success": False,
                "message": "Invalid frame."
            }), 400

        results = get_model().predict(
            source=frame,
            imgsz=640,
            conf=0.20,
            iou=0.50,
            max_det=500,
            classes=[0],
            device="cpu",
            verbose=False
        )

        result = results[0]

        person_count = (
            int((result.boxes.cls == 0).sum().item())
            if result.boxes is not None else 0
        )

        density = classify_density(person_count)

            

        connection = get_db()

        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")

        connection.execute("""
            INSERT INTO location_status
            (location_id, owner_id, person_count, density, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(location_id) DO UPDATE SET
                owner_id = excluded.owner_id,
                person_count = excluded.person_count,
                density = excluded.density,
                updated_at = excluded.updated_at
        """, (
            location_id,
            owner_id,
            person_count,
            density,
            timestamp
        ))

        last_reading = connection.execute("""
            SELECT created_at
            FROM crowd_history
            WHERE location_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (location_id,)).fetchone()

        should_save_history = False

        if last_reading is None:
            should_save_history = True
        else:
            previous_time = datetime.strptime(
                last_reading["created_at"],
                "%Y-%m-%d %H:%M:%S"
            )

            elapsed = (current_time - previous_time).total_seconds()

            if elapsed >= 15:
                should_save_history = True

        if should_save_history:
            connection.execute("""
                INSERT INTO crowd_history
                (location_id, owner_id, person_count, density, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                location_id,
                owner_id,
                person_count,
                density,
                timestamp
            ))

        connection.commit()
        connection.close()

        # Keep the latest owner status for the existing status endpoint.
        latest_live_status[owner_id] = {
            "active": True,
            "person_count": person_count,
            "density": density,
            "location_id": location_id
        }

        # Track alert state separately for each location.
        alert_key = (owner_id, location_id)

        if (
            density == "High"
            and not live_alert_active.get(alert_key, False)
        ):

            connection = get_db()

            connection.execute("""
                INSERT INTO live_alerts
                (
                    person_count,
                    density,
                    source,
                    created_at,
                    owner_id,
                    location_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                person_count,
                density,
                "Live Camera",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                owner_id,
                location_id
            ))

            connection.commit()
            connection.close()

            live_alert_active[alert_key] = True

        elif density != "High":

            live_alert_active[alert_key] = False

        success, buffer = cv2.imencode(
            ".jpg",
            result.plot()
        )

        if not success:
            raise RuntimeError("Could not encode frame.")

        image_base64 = base64.b64encode(
            buffer.tobytes()
        ).decode("utf-8")

        return jsonify({
            "success": True,
            "person_count": person_count,
            "density": density,
            "location_id": location_id,
            "image": "data:image/jpeg;base64," + image_base64
        })

    except Exception as error:

        print("Live detection error:", error)

        return jsonify({
            "success": False,
            "message": "Live AI detection failed."
        }), 500



@app.route("/live-detect-status")
@login_required
def live_detect_status():

    owner_id = session["user_id"]

    return jsonify(
        latest_live_status.get(owner_id, {
            "active": False,
            "person_count": 0,
            "density": "Waiting"
        })
    )



@app.route("/live-detect-stop", methods=["POST"])
@login_required
def live_detect_stop():

    owner_id = session["user_id"]

    location_id = request.form.get("location_id")

    latest_live_status[owner_id] = {
        "active": False,
        "person_count": 0,
        "density": "Waiting",
        "location_id": None
    }

    if location_id:
        try:
            location_id = int(location_id)

            connection = get_db()

            location = connection.execute("""
                SELECT id FROM locations
                WHERE id = ? AND owner_id = ?
            """, (location_id, owner_id)).fetchone()

            connection.close()

            if location:
                live_alert_active[(owner_id, location_id)] = False

        except (ValueError, TypeError):
            pass

    else:
        # Reset all alert states belonging to this owner.
        for key in list(live_alert_active.keys()):
            if isinstance(key, tuple) and key[0] == owner_id:
                live_alert_active[key] = False

    return jsonify({
        "success": True,
        "message": "Monitoring stopped."
    })



@app.route("/api/cameras/register", methods=["POST"])
@login_required
def register_camera():

    owner_id = session["user_id"]

    if session.get("role") != "owner":
        return jsonify({
            "success": False,
            "message": "Only location owners can register cameras."
        }), 403

    data = request.get_json(silent=True) or {}

    camera_name = data.get("camera_name", "").strip()
    camera_type = data.get("camera_type", "").strip()
    location_id = data.get("location_id")
    rtsp_url = data.get("rtsp_url", "").strip()

    allowed_types = ["ip_cctv", "usb", "mobile"]

    if not camera_name or camera_type not in allowed_types or not location_id:
        return jsonify({
            "success": False,
            "message": "Provide a camera name, valid camera type and location."
        }), 400

    # IP CCTV cameras require an RTSP address.
    encrypted_rtsp_url = None

    if camera_type == "ip_cctv":
        if not rtsp_url.startswith(("rtsp://", "rtsps://")):
            return jsonify({
                "success": False,
                "message": "Enter a valid RTSP or RTSPS address."
            }), 400

        try:
            encrypted_rtsp_url = rtsp_cipher.encrypt(
                rtsp_url.encode("utf-8")
            ).decode("utf-8")
        except Exception:
            return jsonify({
                "success": False,
                "message": "Could not secure the RTSP address."
            }), 500

    try:
        location_id = int(location_id)
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "message": "Invalid location ID."
        }), 400

    connection = get_db()

    try:
        location = connection.execute("""
            SELECT id FROM locations
            WHERE id = ? AND owner_id = ?
        """, (location_id, owner_id)).fetchone()

        if not location:
            return jsonify({
                "success": False,
                "message": "Location not found or access denied."
            }), 403

        camera_token = secrets.token_urlsafe(32)

        token_hash = hashlib.sha256(
            camera_token.encode("utf-8")
        ).hexdigest()

        cursor = connection.execute("""
            INSERT INTO camera_devices (
                owner_id,
                location_id,
                camera_name,
                camera_type,
                token_hash,
                encrypted_rtsp_url,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            owner_id,
            location_id,
            camera_name,
            camera_type,
            token_hash,
            encrypted_rtsp_url,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        camera_id = cursor.lastrowid
        connection.commit()

        return jsonify({
            "success": True,
            "message": "Camera registered successfully.",
            "camera_id": camera_id,
            "camera_token": camera_token
        })

    except Exception as error:
        connection.rollback()
        print("Camera registration error:", error)

        return jsonify({
            "success": False,
            "message": "Could not register camera."
        }), 500

    finally:
        connection.close()


@app.route("/api/cameras", methods=["GET"])
@login_required
def get_cameras():

    owner_id = session["user_id"]

    if session.get("role") != "owner":
        return jsonify({
            "success": False,
            "message": "Access denied."
        }), 403

    connection = get_db()

    try:
        cameras = connection.execute("""
            SELECT
                c.id,
                c.camera_name,
                c.camera_type,
                c.location_id,
                c.is_active,
                c.last_seen_at,
                l.location_name
            FROM camera_devices c
            JOIN locations l ON c.location_id = l.id
            WHERE c.owner_id = ?
            ORDER BY c.id DESC
        """, (owner_id,)).fetchall()

        return jsonify({
            "success": True,
            "cameras": [
                {
                    "id": camera["id"],
                    "camera_name": camera["camera_name"],
                    "camera_type": camera["camera_type"],
                    "location_id": camera["location_id"],
                    "location_name": camera["location_name"],
                    "is_active": bool(camera["is_active"]),
                    "last_seen_at": camera["last_seen_at"]
                }
                for camera in cameras
            ]
        })

    except Exception as error:
        print("Camera listing error:", error)

        return jsonify({
            "success": False,
            "message": "Could not load cameras."
        }), 500

    finally:
        connection.close()


@app.route("/api/cameras/<int:camera_id>/connect", methods=["POST"])
@login_required
def connect_ip_camera(camera_id):

    owner_id = session["user_id"]

    if session.get("role") != "owner":
        return jsonify({"success": False, "message": "Access denied."}), 403

    connection = get_db()

    try:
        camera = connection.execute("""
            SELECT id, camera_name, location_id, encrypted_rtsp_url
            FROM camera_devices
            WHERE id = ? AND owner_id = ? AND camera_type = 'ip_cctv'
        """, (camera_id, owner_id)).fetchone()
    finally:
        connection.close()

    if not camera:
        return jsonify({
            "success": False,
            "message": "IP camera not found."
        }), 404

    if not camera["encrypted_rtsp_url"]:
        return jsonify({
            "success": False,
            "message": "No RTSP address is saved for this camera."
        }), 400

    with camera_workers_lock:
        existing_worker = camera_workers.get(camera_id)

        if existing_worker:
            if existing_worker["thread"].is_alive():
                return jsonify({
                    "success": False,
                    "message": "This camera is already connecting or connected."
                }), 409

            camera_workers.pop(camera_id, None)

    try:
        rtsp_url = rtsp_cipher.decrypt(
            camera["encrypted_rtsp_url"].encode("utf-8")
        ).decode("utf-8")

        capture = cv2.VideoCapture(
    rtsp_url,
    cv2.CAP_FFMPEG,
    [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000
    ]
)

        if not capture.isOpened():
            capture.release()
            return jsonify({
                "success": False,
                "message": "Could not open RTSP stream. Check the address and network."
            }), 400

        # Verify that the camera actually provides a frame.
        success, test_frame = capture.read()

        if not success or test_frame is None:
            capture.release()
            return jsonify({
                "success": False,
                "message": "RTSP stream opened, but no video frame was received."
            }), 400

        stop_event = threading.Event()

        worker_thread = threading.Thread(
            target=run_ip_camera,
            args=(
                camera_id,
                owner_id,
                camera["location_id"],
                camera["camera_name"],
                capture,
                stop_event
            ),
            daemon=True
        )

        with camera_workers_lock:
            camera_workers[camera_id] = {
                "thread": worker_thread,
                "stop_event": stop_event,
                "owner_id": owner_id
            }

        worker_thread.start()

        return jsonify({
            "success": True,
            "message": "IP camera connected. AI monitoring started."
        })

    except Exception as error:
        print("IP camera connection error:", error)

        return jsonify({
            "success": False,
            "message": "Could not connect to the IP camera."
        }), 500


@app.route("/api/cameras/<int:camera_id>/disconnect", methods=["POST"])
@login_required
def disconnect_ip_camera(camera_id):

    owner_id = session["user_id"]

    if session.get("role") != "owner":
        return jsonify({
            "success": False,
            "message": "Access denied."
        }), 403

    connection = get_db()

    try:
        camera = connection.execute("""
            SELECT id FROM camera_devices
            WHERE id = ? AND owner_id = ? AND camera_type = 'ip_cctv'
        """, (camera_id, owner_id)).fetchone()
    finally:
        connection.close()

    if not camera:
        return jsonify({
            "success": False,
            "message": "IP camera not found."
        }), 404

    with camera_workers_lock:
        worker = camera_workers.get(camera_id)

        if not worker:
            return jsonify({
                "success": False,
                "message": "Camera is already disconnected."
            }), 400

        worker["stop_event"].set()
        worker_thread = worker["thread"]

    # Wait briefly for the camera worker to release its stream.
    worker_thread.join(timeout=3)

    if worker_thread.is_alive():
        return jsonify({
            "success": False,
            "message": "Camera is still stopping. Please try again."
        }), 409

    return jsonify({
        "success": True,
        "message": "IP camera disconnected successfully."
    })


@app.route("/api/cameras/<int:camera_id>/remove", methods=["POST"])
@login_required
def remove_ip_camera(camera_id):

    owner_id = session["user_id"]

    if session.get("role") != "owner":
        return jsonify({"success": False, "message": "Access denied."}), 403

    with camera_workers_lock:
        worker = camera_workers.get(camera_id)

        if worker:
            if worker["owner_id"] != owner_id:
                return jsonify({"success": False, "message": "Access denied."}), 403

            worker["stop_event"].set()
            thread = worker["thread"]
        else:
            thread = None

    if thread:
        thread.join(timeout=3)

        if thread.is_alive():
            return jsonify({
                "success": False,
                "message": "Camera is still stopping. Try again."
            }), 409

    connection = get_db()

    try:
        cursor = connection.execute("""
            DELETE FROM camera_devices
            WHERE id = ? AND owner_id = ? AND camera_type = 'ip_cctv'
        """, (camera_id, owner_id))

        if cursor.rowcount == 0:
            connection.rollback()
            return jsonify({"success": False, "message": "Camera not found."}), 404

        connection.commit()

        return jsonify({
            "success": True,
            "message": "Camera removed successfully."
        })

    except Exception as error:
        connection.rollback()
        print("Camera removal error:", error)
        return jsonify({"success": False, "message": "Could not remove camera."}), 500

    finally:
        connection.close()


@app.route("/api/cameras/frame", methods=["POST"])
def receive_camera_frame():

    connection = None

    try:
        # Read the private token from the request header.
        camera_token = request.headers.get("X-Camera-Token", "").strip()

        if not camera_token:
            return jsonify({
                "success": False,
                "message": "Camera authentication required."
            }), 401

        token_hash = hashlib.sha256(
            camera_token.encode("utf-8")
        ).hexdigest()

        connection = get_db()

        camera = connection.execute("""
            SELECT
                id, owner_id, location_id, camera_name
            FROM camera_devices
            WHERE token_hash = ? AND is_active = 1
        """, (token_hash,)).fetchone()

        if not camera:
            return jsonify({
                "success": False,
                "message": "Invalid or inactive camera token."
            }), 401

        # Receive the camera image.
        frame_file = request.files.get("frame")

        if frame_file is None:
            return jsonify({
                "success": False,
                "message": "No camera frame received."
            }), 400

        image_bytes = frame_file.read(5 * 1024 * 1024 + 1)

        if not image_bytes or len(image_bytes) > 5 * 1024 * 1024:
            return jsonify({
                "success": False,
                "message": "Frame is empty or exceeds the 5 MB limit."
            }), 400

        image_array = np.frombuffer(
            image_bytes,
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        if frame is None:
            return jsonify({
                "success": False,
                "message": "Invalid image frame."
            }), 400

        # Run YOLO person detection.
        results = get_model().predict(
            source=frame,
            imgsz=640,
            conf=0.20,
            iou=0.50,
            max_det=500,
            classes=[0],
            device="cpu",
            verbose=False
        )

        result = results[0]

        person_count = (
            int((result.boxes.cls == 0).sum().item())
            if result.boxes is not None else 0
        )

        density = classify_density(person_count)

        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")

        owner_id = camera["owner_id"]
        location_id = camera["location_id"]
        camera_id = camera["id"]

        # Update the location's latest crowd status.
        connection.execute("""
            INSERT INTO location_status
            (location_id, owner_id, person_count, density, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(location_id) DO UPDATE SET
                owner_id = excluded.owner_id,
                person_count = excluded.person_count,
                density = excluded.density,
                updated_at = excluded.updated_at
        """, (
            location_id,
            owner_id,
            person_count,
            density,
            timestamp
        ))

        # Save a history reading every 15 seconds.
        last_reading = connection.execute("""
            SELECT created_at
            FROM crowd_history
            WHERE location_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (location_id,)).fetchone()

        should_save_history = last_reading is None

        if last_reading is not None:
            previous_time = datetime.strptime(
                last_reading["created_at"],
                "%Y-%m-%d %H:%M:%S"
            )

            should_save_history = (
                current_time - previous_time
            ).total_seconds() >= 15

        if should_save_history:
            connection.execute("""
                INSERT INTO crowd_history
                (location_id, owner_id, person_count, density, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                location_id,
                owner_id,
                person_count,
                density,
                timestamp
            ))

        # Record when this camera last sent a frame.
        connection.execute("""
            UPDATE camera_devices
            SET last_seen_at = ?
            WHERE id = ? AND owner_id = ?
        """, (timestamp, camera_id, owner_id))

        # Record a high-density alert for this camera.
        alert_key = (owner_id, location_id, camera_id)

        if density == "High" and not live_alert_active.get(alert_key, False):

            connection.execute("""
                INSERT INTO live_alerts
                (person_count, density, source, created_at, owner_id, location_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                person_count,
                density,
                "Remote Camera: " + camera["camera_name"],
                timestamp,
                owner_id,
                location_id
            ))

            live_alert_active[alert_key] = True

        elif density != "High":
            live_alert_active[alert_key] = False

        connection.commit()

        return jsonify({
            "success": True,
            "camera_id": camera_id,
            "camera_name": camera["camera_name"],
            "location_id": location_id,
            "person_count": person_count,
            "density": density,
            "updated_at": timestamp
        })

    except Exception as error:
        if connection:
            connection.rollback()

        print("Remote camera frame error:", error)

        return jsonify({
            "success": False,
            "message": "Camera frame processing failed."
        }), 500

    finally:
        if connection:
            connection.close()


@app.route("/debug/detections")
@login_required
def debug_detections():

    connection = get_db()

    rows = connection.execute("""
        SELECT id, owner_id, location_id,
               person_count, density, created_at
        FROM detections
        ORDER BY id DESC
        LIMIT 10
    """).fetchall()

    connection.close()

    return jsonify([
        dict(row) for row in rows
    ])


@app.route("/debug/crowd-history")
@login_required
def debug_crowd_history():

    owner_id = session["user_id"]

    connection = get_db()

    rows = connection.execute("""
        SELECT
            id,
            location_id,
            person_count,
            density,
            created_at
        FROM crowd_history
        WHERE owner_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (owner_id,)).fetchall()

    connection.close()

    return jsonify({
        "success": True,
        "history": [dict(row) for row in rows]
    })



@app.route("/api/crowd-trend/<int:location_id>")
def crowd_trend(location_id):

    connection = get_db()

    rows = connection.execute("""
        SELECT person_count, created_at
        FROM crowd_history
        WHERE location_id = ?
        ORDER BY id DESC
        LIMIT 5
    """, (location_id,)).fetchall()

    connection.close()

    if len(rows) < 2:
        return jsonify({
            "success": True,
            "trend": "Insufficient data",
            "change": 0
        })

    latest = rows[0]["person_count"]
    previous = rows[-1]["person_count"]

    change = latest - previous

    if change > 0:
        trend = "Increasing"
    elif change < 0:
        trend = "Decreasing"
    else:
        trend = "Stable"

    return jsonify({
        "success": True,
        "trend": trend,
        "latest_count": latest,
        "previous_count": previous,
        "change": change
    })


@app.route("/api/crowd-history/<int:location_id>")
def public_crowd_history(location_id):

    connection = get_db()

    # Only allow access to publicly listed locations
    location = connection.execute("""
        SELECT id FROM locations
        WHERE id = ? AND is_public = 1
    """, (location_id,)).fetchone()

    if not location:
        connection.close()
        return jsonify({
            "success": False,
            "message": "Public location not found."
        }), 404

    # Get readings from the last hour
    rows = connection.execute("""
        SELECT person_count, created_at
        FROM crowd_history
        WHERE location_id = ?
        AND created_at >= datetime('now', 'localtime', '-1 hour')
        ORDER BY id ASC
    """, (location_id,)).fetchall()

    connection.close()

    counts = [row["person_count"] for row in rows]

    return jsonify({
        "success": True,
        "history": [
            {
                "people": row["person_count"],
                "time": row["created_at"]
            }
            for row in rows
        ],
        "peak": max(counts) if counts else 0,
        "average": round(sum(counts) / len(counts), 1) if counts else 0,
        "total_readings": len(counts)
    })



# ======================================
# RUN SERVER
# ======================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )

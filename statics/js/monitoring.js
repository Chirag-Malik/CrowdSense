
document.addEventListener("DOMContentLoaded", function () {
    const video = document.getElementById("live-camera");
    const canvas = document.getElementById("camera-canvas");
    const startButton = document.getElementById("start-camera");
    const stopButton = document.getElementById("stop-camera");
    const locationSelect = document.getElementById("monitored-location");

    const cameraStatus = document.getElementById("camera-status");
    const monitoringStatus = document.getElementById("monitoring-status");
    const personCount = document.getElementById("live-person-count");
    const density = document.getElementById("live-density");
    const liveAlert = document.getElementById("live-alert");

    const cameraForm = document.getElementById("ip-camera-form");
    const cameraNameInput = document.getElementById("ip-camera-name");
    const rtspInput = document.getElementById("ip-camera-rtsp");
    const registerButton = document.getElementById("register-ip-camera");
    const cameraMessage = document.getElementById("ip-camera-message");
    const cameraList = document.getElementById("ip-camera-list");
    const tokenBox = document.getElementById("new-camera-token");
    const tokenValue = document.getElementById("camera-token-value");
    const copyTokenButton = document.getElementById("copy-camera-token");

    let cameraStream = null;
    let monitoringActive = false;
    let selectedLocationId = null;

    const ipCameraStates = new Map();

    const detectionImage = document.createElement("img");
    detectionImage.alt = "Live AI detection results";
    detectionImage.style.width = "100%";
    detectionImage.style.maxHeight = "450px";
    detectionImage.style.objectFit = "contain";
    detectionImage.style.background = "#000";
    detectionImage.style.borderRadius = "12px";
    detectionImage.style.marginTop = "15px";
    detectionImage.style.display = "none";

    video.insertAdjacentElement("afterend", detectionImage);

    // LOAD LOCATIONS
    async function loadLocations() {
        try {
            const response = await fetch("/api/owner-locations");

            if (!response.ok) {
                throw new Error("Could not load locations.");
            }

            const data = await response.json();
            const locations = data.locations || [];

            locationSelect.innerHTML =
                '<option value="">Select a location</option>';

            locations.forEach(location => {
                const option = document.createElement("option");
                option.value = location.id;
                option.textContent =
                    location.location_name + " - " + location.address;

                locationSelect.appendChild(option);
            });

            if (!locations.length) {
                locationSelect.innerHTML =
                    '<option value="">Register a location first</option>';

                startButton.disabled = true;
                registerButton.disabled = true;
                cameraStatus.textContent = "Register a location first.";
            } else {
                startButton.disabled = false;
                registerButton.disabled = false;
            }

        } catch (error) {
            cameraStatus.textContent = error.message;

            locationSelect.innerHTML =
                '<option value="">Unable to load locations</option>';

            startButton.disabled = true;
            registerButton.disabled = true;
        }
    }

    // EXISTING WEBCAM FRAME PROCESSING
    async function processFrame() {
        if (!monitoringActive) return;

        try {
            if (video.readyState < 2) {
                setTimeout(processFrame, 500);
                return;
            }

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;

            const context = canvas.getContext("2d");

            context.drawImage(
                video,
                0,
                0,
                canvas.width,
                canvas.height
            );

            const blob = await new Promise(resolve =>
                canvas.toBlob(resolve, "image/jpeg", 0.70)
            );

            if (!blob) {
                throw new Error("Could not capture camera frame.");
            }

            const formData = new FormData();

            formData.append("frame", blob, "camera-frame.jpg");
            formData.append("location_id", selectedLocationId);

            const response = await fetch("/live-detect", {
                method: "POST",
                body: formData
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.message || "AI detection failed.");
            }

            if (!monitoringActive) return;

            personCount.textContent = data.person_count;
            density.textContent = data.density;

            detectionImage.src = data.image;
            detectionImage.style.display = "block";

            if (data.density === "High") {
                liveAlert.textContent =
                    "HIGH CROWD ALERT: " +
                    data.person_count +
                    " people detected!";

                liveAlert.style.background = "#5c2020";
                liveAlert.style.color = "#fff";
                liveAlert.style.padding = "15px";
                liveAlert.style.marginTop = "15px";
                liveAlert.style.borderRadius = "10px";
            } else {
                liveAlert.textContent = "";
                liveAlert.style.padding = "0";
            }

            cameraStatus.textContent = "Webcam connected - AI active";
            monitoringStatus.textContent = "Monitoring";

        } catch (error) {
            console.error("Webcam monitoring error:", error);

            if (monitoringActive) {
                cameraStatus.textContent = "AI error: " + error.message;
            }
        }

        if (monitoringActive) {
            setTimeout(processFrame, 1200);
        }
    }

    // START WEBCAM
    
startButton.addEventListener("click", async function () {
    selectedLocationId = locationSelect.value;

    if (!selectedLocationId) {
        cameraStatus.textContent = "Please select a location.";
        return;
    }

    // Check whether browser camera access is supported
    if (
        !window.isSecureContext ||
        !navigator.mediaDevices ||
        !navigator.mediaDevices.getUserMedia
    ) {
        cameraStatus.textContent =
            "Camera requires HTTPS. Open CrowdSense using a secure HTTPS connection.";

        monitoringStatus.textContent = "Offline";
        return;
    }

    try {
        startButton.disabled = true;
        locationSelect.disabled = true;

        cameraStatus.textContent = "Connecting to webcam...";

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: "user",
                width: { ideal: 640 },
                height: { ideal: 480 }
            },
            audio: false
        });

        video.srcObject = cameraStream;
        await video.play();

        monitoringActive = true;

        cameraStatus.textContent =
            "Webcam connected. Starting AI...";

        monitoringStatus.textContent = "Starting";
        stopButton.disabled = false;

        processFrame();

    } catch (error) {
        cameraStatus.textContent =
            "Camera error: " + error.message;

        monitoringStatus.textContent = "Offline";

        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
            cameraStream = null;
        }

        video.srcObject = null;

        startButton.disabled = false;
        stopButton.disabled = true;
        locationSelect.disabled = false;
    }
});


    // STOP WEBCAM
    stopButton.addEventListener("click", async function () {
        monitoringActive = false;

        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
            cameraStream = null;
        }

        video.srcObject = null;

        try {
            const stopData = new FormData();

            stopData.append("location_id", selectedLocationId);

            await fetch("/live-detect-stop", {
                method: "POST",
                body: stopData
            });

        } catch (error) {
            console.error(
                "Could not update webcam status:",
                error
            );
        }

        cameraStatus.textContent = "Webcam is offline";
        monitoringStatus.textContent = "Offline";
        personCount.textContent = "0";
        density.textContent = "Waiting";
        liveAlert.textContent = "";

        detectionImage.style.display = "none";

        startButton.disabled = false;
        stopButton.disabled = true;
        locationSelect.disabled = false;
    });

    // COPY ONE-TIME CAMERA TOKEN
    copyTokenButton.addEventListener("click", async function () {
        try {
            await navigator.clipboard.writeText(tokenValue.textContent);
            copyTokenButton.textContent = "Copied!";

        } catch (error) {
            cameraMessage.textContent =
                "Copy failed. Select and copy the token manually.";
        }
    });

    // REGISTER IP CAMERA
    cameraForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const cameraName = cameraNameInput.value.trim();
        const rtspUrl = rtspInput.value.trim();
        const locationId = locationSelect.value;

        if (!locationId) {
            cameraMessage.textContent = "Select a location first.";
            return;
        }

        if (!cameraName || !rtspUrl) {
            cameraMessage.textContent =
                "Enter a camera name and RTSP address.";
            return;
        }

        registerButton.disabled = true;
        cameraMessage.textContent = "Registering camera...";
        tokenBox.hidden = true;

        try {
            const response = await fetch("/api/cameras/register", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    camera_name: cameraName,
                    camera_type: "ip_cctv",
                    location_id: locationId,
                    rtsp_url: rtspUrl
                })
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.message || "Registration failed."
                );
            }

            cameraMessage.textContent = data.message;

            tokenValue.textContent = data.camera_token || "";
            tokenBox.hidden = !data.camera_token;

            cameraForm.reset();

            await loadCameras();

        } catch (error) {
            cameraMessage.textContent = error.message;

        } finally {
            registerButton.disabled = false;
        }
    });

    // LOAD REGISTERED CAMERAS
    async function loadCameras() {
        cameraList.textContent = "Loading cameras...";

        try {
            const response = await fetch("/api/cameras");
            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.message || "Could not load cameras."
                );
            }

            cameraList.replaceChildren();

            const cameras = (data.cameras || []).filter(
                camera => camera.camera_type === "ip_cctv"
            );

            if (!cameras.length) {
                cameraList.textContent =
                    "No IP cameras registered yet.";
                return;
            }

            cameras.forEach(camera => {
                const card = document.createElement("div");

                card.style.cssText =
                    "padding:15px;margin-top:12px;" +
                    "border:1px solid #888;border-radius:10px;";

                const name = document.createElement("h3");
                name.textContent = camera.camera_name;

                const location = document.createElement("p");
                location.textContent =
                    "Location: " + camera.location_name;

                const status = document.createElement("p");

                status.textContent = ipCameraStates.has(camera.id)
                    ? "Status: Connected"
                    : "Status: Not connected in this session";

                const connect = document.createElement("button");
                connect.type = "button";
                connect.textContent = "Connect";

                const disconnect = document.createElement("button");
                disconnect.type = "button";
                disconnect.textContent = "Disconnect";
                disconnect.style.marginLeft = "8px";

                const remove = document.createElement("button");
                remove.type = "button";
                remove.textContent = "Remove";
                remove.style.marginLeft = "8px";

                connect.disabled = ipCameraStates.has(camera.id);
                disconnect.disabled = !ipCameraStates.has(camera.id);

                // CONNECT IP CAMERA
                connect.addEventListener("click", async function () {
                    connect.disabled = true;
                    status.textContent = "Status: Connecting...";

                    const controller = new AbortController();

                    const timeout = setTimeout(
                        () => controller.abort(),
                        12000
                    );

                    try {
                        const result = await fetch(
                            `/api/cameras/${camera.id}/connect`,
                            {
                                method: "POST",
                                signal: controller.signal
                            }
                        );

                        const resultData = await result.json();

                        if (!result.ok || !resultData.success) {
                            throw new Error(
                                resultData.message || "Connection failed."
                            );
                        }

                        ipCameraStates.set(camera.id, true);

                        status.textContent =
                            "Status: Connected - AI running";

                        connect.disabled = true;
                        disconnect.disabled = false;

                    } catch (error) {
                        status.textContent =
                            "Status: Connection failed";

                        cameraMessage.textContent =
                            error.name === "AbortError"
                                ? "Connection timed out. Check the RTSP address."
                                : error.message;

                        connect.disabled = false;
                        disconnect.disabled = true;

                    } finally {
                        clearTimeout(timeout);
                    }
                });

                // DISCONNECT IP CAMERA
                disconnect.addEventListener("click", async function () {
                    disconnect.disabled = true;

                    try {
                        const result = await fetch(
                            `/api/cameras/${camera.id}/disconnect`,
                            { method: "POST" }
                        );

                        const resultData = await result.json();

                        if (!result.ok || !resultData.success) {
                            throw new Error(
                                resultData.message || "Disconnect failed."
                            );
                        }

                        ipCameraStates.delete(camera.id);

                        status.textContent = "Status: Disconnected";
                        connect.disabled = false;
                        disconnect.disabled = true;

                    } catch (error) {
                        cameraMessage.textContent = error.message;
                        disconnect.disabled = false;
                    }
                });

                // REMOVE IP CAMERA
                remove.addEventListener("click", async function () {
                    if (!confirm("Remove " + camera.camera_name + "?")) {
                        return;
                    }

                    remove.disabled = true;

                    try {
                        const result = await fetch(
                            `/api/cameras/${camera.id}/remove`,
                            { method: "POST" }
                        );

                        const resultData = await result.json();

                        if (!result.ok || !resultData.success) {
                            throw new Error(
                                resultData.message || "Remove failed."
                            );
                        }

                        ipCameraStates.delete(camera.id);

                        await loadCameras();

                    } catch (error) {
                        cameraMessage.textContent = error.message;
                        remove.disabled = false;
                    }
                });

                card.append(
                    name,
                    location,
                    status,
                    connect,
                    disconnect,
                    remove
                );

                cameraList.appendChild(card);
            });

        } catch (error) {
            cameraList.textContent = error.message;
        }
    }

    // INITIAL LOAD
    loadLocations();
    loadCameras();
});

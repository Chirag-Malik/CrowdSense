
// ======================================
// CROWDSENSE - MAIN JAVASCRIPT
// ======================================


// IMAGE UPLOAD ELEMENTS
const imageInput = document.getElementById("image-input");
const uploadButton = document.getElementById("upload-button");
const imageMessage = document.getElementById("image-message");
const imagePreview = document.getElementById("image-preview");


// CAMERA ELEMENTS
const cameraButton = document.getElementById("camera-button");
const cameraPreview = document.getElementById("camera-preview");
const cameraMessage = document.getElementById("camera-message");
const cameraPlaceholder = document.getElementById("camera-placeholder");
const cameraStatus = document.getElementById("camera-status");


// VARIABLES
let selectedImage = null;
let cameraStream = null;


// ======================================
// IMAGE SELECTION AND PREVIEW
// ======================================

imageInput.addEventListener("change", function () {

    const file = imageInput.files[0];

    if (!file) return;

    const allowedTypes = [
        "image/jpeg",
        "image/png",
        "image/webp"
    ];

    if (!allowedTypes.includes(file.type)) {

        imageMessage.textContent =
            "Please select a JPG, PNG or WEBP image.";

        imageInput.value = "";
        selectedImage = null;

        return;
    }

    if (file.size > 8 * 1024 * 1024) {

        imageMessage.textContent =
            "Image must be smaller than 8 MB.";

        imageInput.value = "";
        selectedImage = null;

        return;
    }

    selectedImage = file;

    const previewURL = URL.createObjectURL(file);

    imagePreview.src = previewURL;
    imagePreview.style.display = "block";

    imageMessage.textContent =
        "Selected: " + file.name;

    uploadButton.textContent = "Upload Image";

});


// ======================================
// UPLOAD IMAGE TO FLASK SERVER
// ======================================

uploadButton.addEventListener("click", async function () {

    if (!selectedImage) {

        imageMessage.textContent =
            "Please select an image first.";

        imageInput.click();

        return;
    }

    const formData = new FormData();

    formData.append("image", selectedImage);

    uploadButton.disabled = true;
    uploadButton.textContent = "Uploading...";

    imageMessage.textContent =
        "Uploading image to CrowdSense server...";

    try {

        const response = await fetch("/upload", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || "Upload failed.");
        }

        imageMessage.textContent =
            "Success! Image uploaded: " + data.original_name;

        uploadButton.textContent = "Select Another Image";

        selectedImage = null;
        imageInput.value = "";

    }

    catch (error) {

        imageMessage.textContent =
            "Upload error: " + error.message;

        uploadButton.textContent = "Try Again";

    }

    finally {

        uploadButton.disabled = false;

    }

});


// ======================================
// LIVE CAMERA PREVIEW
// ======================================

cameraButton.addEventListener("click", async function () {

    // STOP CAMERA
    if (cameraStream) {

        cameraStream.getTracks().forEach(track => {
            track.stop();
        });

        cameraStream = null;

        cameraPreview.srcObject = null;
        cameraPreview.style.display = "none";

        cameraPlaceholder.style.display = "block";

        cameraButton.textContent = "Enable Camera";

        cameraMessage.textContent = "Camera inactive.";

        cameraStatus.textContent = "Inactive";

        return;
    }


    // START CAMERA
    try {

        if (!navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia) {

            throw new Error(
                "Camera access is unavailable in this browser."
            );

        }

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: "environment"
            },
            audio: false
        });

        cameraPreview.srcObject = cameraStream;

        cameraPreview.style.display = "block";

        cameraPlaceholder.style.display = "none";

        cameraButton.textContent = "Stop Camera";

        cameraMessage.textContent =
            "Camera preview is active.";

        cameraStatus.textContent = "Active";

    }

    catch (error) {

        cameraStream = null;

        cameraMessage.textContent =
            "Camera error: " + error.message;

        cameraStatus.textContent = "Unavailable";

    }

});


// ======================================
// INITIAL DASHBOARD STATUS
// ======================================

console.log("CrowdSense JavaScript loaded successfully.");


// ======================================
// YOLO AI DETECTION
// ======================================

const detectionInput =
    document.getElementById("detection-input");

const detectButton =
    document.getElementById("detect-button");

const detectionMessage =
    document.getElementById("detection-message");

const detectionResult =
    document.getElementById("detection-result");

const personCount =
    document.getElementById("person-count");

const densityLevel =
    document.getElementById("density-level");

const detectedImage =
    document.getElementById("detected-image");


if (detectButton && detectionInput) {

    detectButton.addEventListener("click", async function () {

        const file = detectionInput.files[0];

        if (!file) {
            detectionMessage.textContent =
                "Please select an image first.";
            return;
        }

        if (!["image/jpeg", "image/png", "image/webp"]
            .includes(file.type)) {

            detectionMessage.textContent =
                "Please select a JPG, PNG or WEBP image.";
            return;
        }

        if (file.size > 8 * 1024 * 1024) {
            detectionMessage.textContent =
                "Maximum image size is 8 MB.";
            return;
        }

        const formData = new FormData();
        formData.append("image", file);

        detectButton.disabled = true;
        detectButton.textContent = "Detecting...";

        detectionMessage.textContent =
            "YOLO is analysing your image. Please wait...";

        detectionResult.style.display = "none";

        try {

            const response = await fetch("/detect", {
                method: "POST",
                body: formData
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.message || "Detection failed."
                );
            }

            personCount.textContent = data.person_count;
            densityLevel.textContent = data.density;

            detectedImage.src =
                data.result_image + "?t=" + Date.now();

            detectionResult.style.display = "block";

            detectionMessage.textContent =
                "AI detection completed successfully!";

        } catch (error) {

            detectionMessage.textContent =
                "Error: " + error.message;

        } finally {

            detectButton.disabled = false;
            detectButton.textContent = "Start AI Detection";

        }

    });

}


document.addEventListener("DOMContentLoaded", function () {

    const input = document.getElementById("detection-input");
    const button = document.getElementById("detect-button");
    const message = document.getElementById("detection-message");
    const resultBox = document.getElementById("detection-result");
    const count = document.getElementById("person-count");
    const density = document.getElementById("density-level");
    const resultImage = document.getElementById("detected-image");

    if (!input || !button || !message) {
        console.error("CrowdSense: Detection elements not found.");
        return;
    }

    // Create or update the visual crowd warning
    function showCrowdWarning(personCount) {

        let warning = document.getElementById("crowd-warning");

        if (!warning) {
            warning = document.createElement("div");
            warning.id = "crowd-warning";

            warning.style.padding = "16px";
            warning.style.marginTop = "15px";
            warning.style.borderRadius = "10px";
            warning.style.background = "#5c2020";
            warning.style.border = "1px solid #ef4444";
            warning.style.color = "#ffffff";
            warning.style.fontWeight = "bold";

            resultBox.prepend(warning);
        }

        warning.textContent =
            "HIGH CROWD ALERT: " + personCount +
            " people detected. Immediate attention recommended.";
    }

    // Send browser notification
    async function sendBrowserNotification(personCount) {

        if (!("Notification" in window)) {
            console.log("Browser notifications are not supported.");
            return;
        }

        try {

            let permission = Notification.permission;

            if (permission === "default") {
                permission = await Notification.requestPermission();
            }

            if (permission === "granted") {

                new Notification("CrowdSense - High Crowd Alert", {
                    body: personCount +
                        " people detected. High crowd density identified.",
                    tag: "crowdsense-high-density"
                });

            }

        } catch (error) {
            console.error("Notification error:", error);
        }
    }

    button.addEventListener("click", async function () {

        const file = input.files[0];

        if (!file) {
            message.textContent = "Please select an image first.";
            return;
        }

        if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
            message.textContent = "Please select JPG, PNG or WEBP.";
            return;
        }

        if (file.size > 8 * 1024 * 1024) {
            message.textContent = "Image must be smaller than 8 MB.";
            return;
        }

        const formData = new FormData();
        formData.append("image", file);

        button.disabled = true;
        button.textContent = "Detecting...";
        message.textContent = "AI is analysing your image. Please wait.";

        if (resultBox) resultBox.style.display = "none";

        try {

            const response = await fetch("/detect", {
                method: "POST",
                body: formData
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.message || "Detection failed.");
            }

            count.textContent = data.person_count;
            density.textContent = data.density;

            resultImage.src = data.result_image + "?t=" + Date.now();

            resultBox.style.display = "block";

            message.textContent = "Detection completed successfully!";

            // HIGH DENSITY ALERT
            if (data.density === "High") {

                showCrowdWarning(data.person_count);

                sendBrowserNotification(data.person_count);

            } else {

                const oldWarning =
                    document.getElementById("crowd-warning");

                if (oldWarning) {
                    oldWarning.remove();
                }

            }

        } catch (error) {

            console.error("CrowdSense detection error:", error);
            message.textContent = "Error: " + error.message;

        } finally {

            button.disabled = false;
            button.textContent = "Start AI Detection";

        }

    });

    console.log("CrowdSense detection script loaded.");

});

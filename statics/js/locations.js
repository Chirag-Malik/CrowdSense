
document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("add-location-form");
    const message = document.getElementById("location-message");
    const locationsContainer = document.getElementById("registered-locations");

    // LOAD REGISTERED LOCATIONS

    async function loadLocations() {

        try {

            const response = await fetch("/api/owner-locations");

            if (!response.ok) {
                throw new Error("Could not load locations");
            }

            const data = await response.json();
            const locations = data.locations || [];

            document.getElementById("location-total").textContent =
                locations.length;

            if (locations.length === 0) {

                locationsContainer.innerHTML =
                    "<p>No locations registered yet.</p>";

                return;
            }

            locationsContainer.innerHTML = "";

            locations.forEach(function (location) {

                const card = document.createElement("div");
                card.className = "stat-card";
                card.style.marginBottom = "15px";

                const heading = document.createElement("h3");
                heading.textContent = location.location_name;

                const address = document.createElement("p");
                address.textContent = location.address;

                const visibility = document.createElement("p");
                visibility.textContent = location.is_public
                    ? "Public visibility: Enabled"
                    : "Public visibility: Disabled";

                // DELETE BUTTON
                const deleteButton = document.createElement("button");

                deleteButton.textContent = "Delete Location";
                deleteButton.type = "button";

                deleteButton.style.background = "#b42323";
                deleteButton.style.color = "#ffffff";
                deleteButton.style.border = "none";
                deleteButton.style.padding = "10px 16px";
                deleteButton.style.borderRadius = "8px";
                deleteButton.style.cursor = "pointer";
                deleteButton.style.marginTop = "12px";

                deleteButton.addEventListener("click", async function () {

                    const confirmed = confirm(
                        "Are you sure you want to delete " +
                        location.location_name +
                        "?\n\nIts crowd history and current monitoring status will also be deleted."
                    );

                    if (!confirmed) return;

                    deleteButton.disabled = true;
                    deleteButton.textContent = "Deleting...";

                    try {

                        const deleteResponse = await fetch(
                            "/owner/delete-location/" + location.id,
                            {
                                method: "POST"
                            }
                        );

                        const result = await deleteResponse.json();

                        if (!deleteResponse.ok || !result.success) {
                            throw new Error(
                                result.message || "Deletion failed."
                            );
                        }

                        message.textContent = result.message;
                        message.style.color = "#22c55e";

                        await loadLocations();

                    } catch (error) {

                        alert(error.message);

                        deleteButton.disabled = false;
                        deleteButton.textContent = "Delete Location";

                    }

                });

                card.appendChild(heading);
                card.appendChild(address);
                card.appendChild(visibility);
                card.appendChild(deleteButton);

                locationsContainer.appendChild(card);

            });

        } catch (error) {

            console.error(error);

            locationsContainer.textContent =
                "Unable to load registered locations.";

        }

    }


    // REGISTER NEW LOCATION

    form.addEventListener("submit", async function (event) {

        event.preventDefault();

        message.textContent = "Registering location...";

        const formData = new FormData(form);

        try {

            const response = await fetch("/owner/add-location", {
                method: "POST",
                body: formData
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.message || "Registration failed");
            }

            message.textContent = "Location registered successfully!";
            message.style.color = "#22c55e";

            form.reset();

            form.querySelector('[name="is_public"]').checked = true;

            await loadLocations();

        } catch (error) {

            message.textContent = error.message;
            message.style.color = "#ef4444";

        }

    });


    // LIVE CAMERA STATUS

    async function updateLocation() {

        try {

            const response = await fetch("/live-detect-status");

            if (!response.ok) {
                throw new Error("Status unavailable");
            }

            const data = await response.json();

            document.getElementById("location-cameras").textContent =
                data.active ? "1" : "0";

            document.getElementById("location-people").textContent =
                data.person_count ?? "--";

            document.getElementById("location-density").textContent =
                data.density ?? "Waiting";

            document.getElementById("location-status").textContent =
                data.active ? "Connected" : "Offline";

            document.getElementById("location-monitoring").textContent =
                data.active ? "Active" : "Inactive";

        } catch (error) {

            document.getElementById("location-status").textContent =
                "Status unavailable";

        }

    }


    loadLocations();
    updateLocation();

    setInterval(updateLocation, 5000);

});

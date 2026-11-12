
document.addEventListener("DOMContentLoaded", () => {

    async function loadAnalytics() {

        try {
            const response = await fetch("/api/analytics");

            if (!response.ok) {
                throw new Error("Unable to fetch analytics data.");
            }

            const data = await response.json();

            // Update statistics cards
            document.getElementById("total-detections").textContent =
                data.total_detections;

            document.getElementById("average-people").textContent =
                data.average_people;

            document.getElementById("highest-people").textContent =
                data.highest_people;

            // Display density distribution
            const densityContainer =
                document.getElementById("density-distribution");

            densityContainer.innerHTML = "";

            const densities = ["Low", "Medium", "High"];

            densities.forEach(level => {

                const item = data.density_distribution.find(
                    entry => entry.density === level
                );

                const count = item ? item.total : 0;

                const row = document.createElement("div");
                row.className = "density-row";

                const label = document.createElement("span");
                label.textContent = level;

                const value = document.createElement("span");
                value.textContent = count + " detections";

                row.appendChild(label);
                row.appendChild(value);

                densityContainer.appendChild(row);

            });

            // Display recent detection history
            const historyBody =
                document.getElementById("detection-history");

            historyBody.innerHTML = "";

            if (data.history.length === 0) {

                const row = document.createElement("tr");
                const cell = document.createElement("td");

                cell.colSpan = 4;
                cell.textContent = "No detection records available yet.";

                row.appendChild(cell);
                historyBody.appendChild(row);

            } else {

                data.history.forEach(record => {

                    const row = document.createElement("tr");

                    const imageCell = document.createElement("td");
                    imageCell.textContent = record.image_name;

                    const peopleCell = document.createElement("td");
                    peopleCell.textContent = record.person_count;

                    const densityCell = document.createElement("td");
                    densityCell.textContent = record.density;

                    const dateCell = document.createElement("td");
                    dateCell.textContent = record.created_at;

                    row.appendChild(imageCell);
                    row.appendChild(peopleCell);
                    row.appendChild(densityCell);
                    row.appendChild(dateCell);

                    historyBody.appendChild(row);

                });

            }

        } catch (error) {

            console.error("Analytics error:", error);

            document.getElementById("density-distribution").textContent =
                "Could not load analytics data.";

            document.getElementById("detection-history").textContent =
                "Could not load detection history.";

        }

    }

    loadAnalytics();

});

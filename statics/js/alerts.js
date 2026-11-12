
document.addEventListener("DOMContentLoaded", async () => {

    const totalElement = document.getElementById("total-alerts");
    const historyElement = document.getElementById("alerts-history");

    try {

        const response = await fetch("/api/alerts");

        if (!response.ok) {
            throw new Error("Could not load alerts.");
        }

        const data = await response.json();

        totalElement.textContent = data.total_alerts;

        historyElement.innerHTML = "";

        if (data.alerts.length === 0) {

            const row = document.createElement("tr");
            const cell = document.createElement("td");

            cell.colSpan = 4;
            cell.textContent = "No high-density alerts recorded yet.";

            row.appendChild(cell);
            historyElement.appendChild(row);

        } else {

            data.alerts.forEach(alert => {

                const row = document.createElement("tr");

                [
                    alert.image_name,
                    alert.person_count,
                    alert.density,
                    alert.created_at
                ].forEach(value => {

                    const cell = document.createElement("td");
                    cell.textContent = value;
                    row.appendChild(cell);

                });

                historyElement.appendChild(row);

            });

        }

    } catch (error) {

        console.error("Alerts error:", error);

        totalElement.textContent = "Error";
        historyElement.textContent = "Unable to load alerts.";

    }

});

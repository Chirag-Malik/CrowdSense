
document.addEventListener("DOMContentLoaded", function () {

    async function loadDashboard() {
        try {
            const [analyticsResponse, alertsResponse] = await Promise.all([
                fetch("/api/analytics"),
                fetch("/api/alerts")
            ]);

            if (!analyticsResponse.ok || !alertsResponse.ok) {
                throw new Error("Could not load dashboard data.");
            }

            const analytics = await analyticsResponse.json();
            const alerts = await alertsResponse.json();

            // Main statistics
            document.getElementById("total-people").textContent =
                analytics.total_detections ?? 0;

            document.getElementById("average-people").textContent =
                Number(analytics.average_people ?? 0).toFixed(1);

            document.getElementById("highest-people").textContent =
                analytics.highest_people ?? 0;

            document.getElementById("high-alerts").textContent =
                alerts.total_alerts ?? 0;

            // Density distribution
            const distribution = analytics.density_distribution || {};

            document.getElementById("low-density").textContent =
                distribution.Low ?? distribution.low ?? 0;

            document.getElementById("medium-density").textContent =
                distribution.Medium ?? distribution.medium ?? 0;

            document.getElementById("high-density").textContent =
                distribution.High ?? distribution.high ?? 0;

            document.getElementById("dashboard-density-status").textContent =
                "Statistics updated successfully.";

            // Recent detection activity
            const activity = document.getElementById("recent-activity");
            activity.replaceChildren();

            const history = analytics.history || [];

            if (history.length === 0) {
                activity.textContent = "No detection records yet.";
                return;
            }

            history.slice(0, 5).forEach(function (item) {
                const entry = document.createElement("p");

                entry.textContent =
                    `${item.image_name || "Detection"} — ` +
                    `${item.person_count ?? 0} people — ` +
                    `${item.density || "Unknown"} — ` +
                    `${item.created_at || ""}`;

                activity.appendChild(entry);
            });

        } catch (error) {
            console.error("Dashboard error:", error);

            document.getElementById("dashboard-density-status").textContent =
                "Unable to load statistics. Check Flask and the APIs.";
        }
    }

    loadDashboard();

});

import { expect, test, type Route } from "@playwright/test";

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

const event = (id: number, title: string, processingStatus: string, readinessStatus = "results_available") => ({
  id,
  sourceRuleId: 1,
  title,
  pageTitle: title,
  url: `https://example.test/${id}`,
  sourceYear: "2026",
  readinessStatus,
  processingStatus,
  isCurrentlyListed: true,
  pdfCount: readinessStatus === "results_available" ? 1 : 0,
  resultPdfCount: readinessStatus === "results_available" ? 1 : 0,
  categoryCounts: {},
  documentCount: readinessStatus === "results_available" ? 1 : 0,
  firstSeenAt: "2026-09-01T00:00:00Z",
  lastSeenInIndexAt: "2026-09-22T00:00:00Z",
  lastCheckedAt: "2026-09-23T00:00:00Z",
  lastChangedAt: "2026-09-23T00:00:00Z",
});

test("source review keeps pending work visible and collapses unchanged imports", async ({ page }) => {
  await page.route("**/api/admin/sources", (route) => json(route, { data: [] }));
  await page.route("**/api/admin/source-events", (route) => json(route, {
    data: [
      event(1, "Fresh results", "results_not_imported"),
      event(2, "Future championship", "waiting_for_results", "pending_no_documents"),
      event(3, "Historic imported championship", "imported_without_manifest_baseline"),
    ],
  }));
  await page.route("**/api/admin/monitor-runs", (route) => json(route, { data: [] }));

  await page.goto("/admin/sources");

  await expect(page.getByRole("heading", { name: "Needs review" })).toBeVisible();
  await expect(page.getByText("Fresh results", { exact: true })).toBeVisible();
  await expect(page.getByText("Future championship", { exact: true })).toBeVisible();

  const imported = page.locator("details").filter({ hasText: "Imported competitions" });
  await expect(imported).not.toHaveAttribute("open", "");
  await expect(page.getByText("Historic imported championship", { exact: true })).not.toBeVisible();

  await imported.locator("summary").click();
  await expect(page.getByText("Historic imported championship", { exact: true })).toBeVisible();
});

import { expect, test, type Page, type Route } from "@playwright/test";

const meet = {
  id: 42,
  name: "Singapore National Age Group Championships 2026",
  date: "2026-03-12",
  end_date: "2026-03-17",
  location: "OCBC Aquatic Centre",
};

const individualResult = {
  type: "individual" as const,
  id: 90,
  event: "Girls 100m Freestyle",
  time: "1:02.53",
  seed_time: "1:03.10",
  placement: 2,
  is_dq: false,
  status: "finished",
  round: "Final",
  swim_date: "2026-03-14",
  qualifier: null,
  swimmer: { id: 7, name: "Tan, Alice", age: 15, team: "Singapore Swimming Club" },
  is_guest: false,
  team_name: null,
  relay_letter: null,
  is_exhibition: false,
  legs: [],
  meet,
};

const relayResult = {
  type: "relay" as const,
  id: 90,
  event: "Girls 4x100m Freestyle Relay",
  time: "4:08.21",
  seed_time: null,
  placement: 1,
  is_dq: false,
  status: "finished",
  round: "Final",
  swim_date: "2026-03-14",
  qualifier: null,
  swimmer: null,
  is_guest: false,
  team_name: "Singapore Swimming Club",
  relay_letter: "A",
  is_exhibition: false,
  legs: [
    {
      leg_number: 1,
      swimmer: { id: 8, name: "Lim, Beth", age: 16, team: "Singapore Swimming Club" },
      split_time: "1:01.00",
      reaction_time: "0.68",
      splits: null,
      is_guest: false,
      gender: "F",
    },
  ],
  meet,
};

const individualDetail = {
  ...individualResult,
  type: undefined,
  team_name: undefined,
  relay_letter: undefined,
  is_exhibition: undefined,
  legs: undefined,
  dq_code: null,
  dq_description: null,
  reaction_time: "0.71",
  splits: JSON.stringify([{ distance: 50, cumulative: "29.90", split: "29.90" }]),
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function stubFilters(page: Page) {
  await page.route("**/api/meets**", (route) =>
    json(route, {
      data: [{ ...meet, result_count: 120, swimmer_count: 48 }],
      pagination: { page: 1, limit: 100, total: 1, total_pages: 1 },
    }),
  );
  await page.route("**/api/events**", (route) =>
    json(route, { events: [individualResult.event, relayResult.event] }),
  );
}

function captureConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("a slower all-results response cannot overwrite newer relay URL state", async ({ page }) => {
  const consoleErrors = captureConsoleErrors(page);
  const requestedRowTypes: string[] = [];
  await stubFilters(page);
  await page.route("**/api/results/all**", async (route) => {
    const rowType = new URL(route.request().url()).searchParams.get("row_type") ?? "all";
    requestedRowTypes.push(rowType);
    if (rowType === "all") await delay(1_800);
    if (rowType === "relay") await delay(80);
    await json(route, {
      data: rowType === "relay" ? [relayResult] : [individualResult],
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    });
  });

  await page.goto("/results?row_type=all");
  await expect.poll(() => requestedRowTypes).toContain("all");
  await page.getByRole("button", { name: "Relay results" }).click();

  await expect(page).toHaveURL(/row_type=relay/);
  await expect(page.getByText(relayResult.event, { exact: true })).toBeVisible();
  await delay(2_000);
  await expect(page.getByText(relayResult.event, { exact: true })).toBeVisible();
  await expect(page.getByText(individualResult.event, { exact: true })).toHaveCount(0);
  expect(requestedRowTypes).toEqual(expect.arrayContaining(["all", "relay"]));
  expect(consoleErrors).toEqual([]);
});

test("Results merges a debounced swimmer search with an immediate row-type change", async ({ page }) => {
  const consoleErrors = captureConsoleErrors(page);
  await stubFilters(page);
  await page.route("**/api/results/all**", (route) =>
    json(route, {
      data: [relayResult],
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    }),
  );

  await page.goto("/results?row_type=all");
  await expect(page.getByText(relayResult.event, { exact: true })).toBeVisible();
  await page.getByPlaceholder("Search by swimmer name...").fill("Alice");
  await page.getByRole("button", { name: "Relay results" }).click();

  await expect.poll(() => {
    const params = new URL(page.url()).searchParams;
    return { rowType: params.get("row_type"), swimmer: params.get("swimmer") };
  }).toEqual({ rowType: "relay", swimmer: "Alice" });
  expect(consoleErrors).toEqual([]);
});

test("Results cancels a pending swimmer debounce when Back restores history", async ({ page }) => {
  await stubFilters(page);
  await page.route("**/api/results/all**", (route) =>
    json(route, { data: [individualResult], pagination: { page: 1, limit: 50, total: 1, total_pages: 1 } }),
  );

  await page.goto("/results?swimmer=before&row_type=all");
  await page.getByRole("button", { name: "Relay results" }).click();
  await expect(page).toHaveURL(/row_type=relay/);
  await page.getByPlaceholder("Search by swimmer name...").fill("current");
  await page.goBack();

  await expect(page).toHaveURL(/swimmer=before/);
  await expect(page).toHaveURL(/row_type=all/);
  await page.waitForTimeout(500);
  await expect(page).toHaveURL(/swimmer=before/);
  await expect(page).toHaveURL(/row_type=all/);
  await expect(page.getByPlaceholder("Search by swimmer name...")).toHaveValue("before");
});

test("the URL restores every results filter on load, refresh, back, and forward", async ({ page }) => {
  const consoleErrors = captureConsoleErrors(page);
  const requests: URL[] = [];
  await stubFilters(page);
  await page.route("**/api/results/all**", async (route) => {
    const requestUrl = new URL(route.request().url());
    requests.push(requestUrl);
    await delay(90);
    await json(route, {
      data: [individualResult],
      pagination: { page: Number(requestUrl.searchParams.get("page") ?? 1), limit: 50, total: 120, total_pages: 3 },
    });
  });

  const event = individualResult.event;
  const initialUrl = `/results?row_type=individual&swimmer=Alice+Tan&event=${encodeURIComponent(event)}&meet_id=42&is_dq=true&page=2`;
  await page.goto(initialUrl);

  const swimmerSearch = page.getByPlaceholder("Search by swimmer name...");
  const eventSearch = page.getByPlaceholder("All Events");
  const meetFilter = page.locator("select");
  await expect(page.getByRole("button", { name: "Individual results" })).toHaveAttribute("aria-pressed", "true");
  await expect(swimmerSearch).toHaveValue("Alice Tan");
  await expect(eventSearch).toHaveValue(event);
  await expect(meetFilter).toHaveValue("42");
  await expect(page.getByRole("button", { name: "DQ Only" })).toBeVisible();
  await expect(page.getByRole("button", { name: "2", exact: true })).toHaveClass(/bg-ssa-navy/);
  await expect.poll(() => requests.at(-1)?.searchParams.toString()).toContain("row_type=individual");

  for (const key of ["row_type", "swimmer", "event", "meet_id", "is_dq", "page"]) {
    expect(requests.at(-1)?.searchParams.get(key)).toBe(new URL(page.url()).searchParams.get(key));
  }

  await page.reload();
  await expect(swimmerSearch).toHaveValue("Alice Tan");
  await expect(eventSearch).toHaveValue(event);
  await expect(meetFilter).toHaveValue("42");
  await expect(page.getByRole("button", { name: "DQ Only" })).toBeVisible();

  await page.getByRole("button", { name: "Relay results" }).click();
  await expect(page).toHaveURL(/row_type=relay/);
  await expect(page).not.toHaveURL(/[?&]page=/);
  await page.goBack();
  await expect(page).toHaveURL(/row_type=individual/);
  await expect(page).toHaveURL(/[?&]page=2/);
  await expect(swimmerSearch).toHaveValue("Alice Tan");
  await expect(eventSearch).toHaveValue(event);
  await expect(page.getByRole("button", { name: "DQ Only" })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/row_type=relay/);
  await expect(page.getByRole("button", { name: "Relay results" })).toHaveAttribute("aria-pressed", "true");

  const clearEvent = page.getByRole("button", { name: "Clear event filter" });
  await expect(clearEvent).toBeVisible();
  await clearEvent.click();
  await expect(page).not.toHaveURL(/[?&]event=/);
  await expect(eventSearch).toHaveValue("");

  await swimmerSearch.fill("Beth Lim");
  await expect(page).toHaveURL(/[?&]swimmer=Beth\+Lim/);
  await eventSearch.click();
  await page.getByRole("button", { name: relayResult.event, exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("event")).toBe(relayResult.event);
  await meetFilter.selectOption("");
  await expect.poll(() => new URL(page.url()).searchParams.has("meet_id")).toBe(false);
  await meetFilter.selectOption("42");
  await expect.poll(() => new URL(page.url()).searchParams.get("meet_id")).toBe("42");
  await page.getByRole("button", { name: "DQ Only" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("is_dq")).toBe(false);
  await page.getByRole("button", { name: "Show DQ" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("is_dq")).toBe("true");
  await page.getByRole("button", { name: "2", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("2");
  await expect.poll(() => requests.at(-1)?.searchParams.get("page")).toBe("2");

  for (const key of ["row_type", "swimmer", "event", "meet_id", "is_dq", "page"]) {
    expect(requests.at(-1)?.searchParams.get(key)).toBe(new URL(page.url()).searchParams.get(key));
  }
  expect(consoleErrors).toEqual([]);
});

test("colliding individual and relay ids retain separate identities and accessible details", async ({ page }) => {
  const consoleErrors = captureConsoleErrors(page);
  let detailRequests = 0;
  await stubFilters(page);
  await page.route("**/api/results/all**", (route) =>
    json(route, {
      data: [individualResult, relayResult],
      pagination: { page: 1, limit: 50, total: 2, total_pages: 1 },
    }),
  );
  await page.route("**/api/results/90", async (route) => {
    detailRequests += 1;
    await delay(180);
    await json(route, individualDetail);
  });

  await page.goto("/results?row_type=all");
  await expect(page.getByText(individualResult.event, { exact: true })).toBeVisible();
  await expect(page.getByText(relayResult.event, { exact: true })).toBeVisible();

  const splitsToggle = page.getByRole("button", { name: "View splits" });
  const relayToggle = page.getByRole("button", { name: "View relay legs" });
  await expect(splitsToggle).toHaveAttribute("aria-expanded", "false");
  await expect(relayToggle).toHaveAttribute("aria-expanded", "false");
  const splitsPanelId = await splitsToggle.getAttribute("aria-controls");
  const relayPanelId = await relayToggle.getAttribute("aria-controls");
  expect(splitsPanelId).toBeTruthy();
  expect(relayPanelId).toBeTruthy();
  expect(splitsPanelId).not.toBe(relayPanelId);

  await relayToggle.click();
  await expect(relayToggle).toHaveAttribute("aria-expanded", "true");
  await expect(splitsToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(`#${relayPanelId}`)).toContainText("Lim Beth");

  await splitsToggle.click();
  await expect(splitsToggle).toHaveAttribute("aria-expanded", "true");
  await expect(relayToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(`#${splitsPanelId}`)).toContainText("29.90");
  await relayToggle.click();
  await splitsToggle.click();
  await expect(page.locator(`#${splitsPanelId}`)).toContainText("29.90");
  expect(detailRequests).toBe(1);
  expect(consoleErrors).toEqual([]);
});

test("Results mobile controls are named, touch-sized, scoped, and cross-linked", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await stubFilters(page);
  await page.route("**/api/results/all**", (route) =>
    json(route, {
      data: [individualResult],
      pagination: { page: 1, limit: 50, total: 120, total_pages: 3 },
    }),
  );
  await page.route("**/api/results/90", (route) => json(route, individualDetail));

  await page.goto("/results?row_type=individual");
  await expect(page.getByText(individualResult.event, { exact: true })).toBeVisible();
  await expect(page.getByLabel("Filter by meet")).toBeVisible();
  await expect(page.locator("th:not([scope='col'])")).toHaveCount(0);
  await expect(page.getByRole("link", { name: meet.name })).toHaveAttribute("href", "/meets/42");
  await expect(page.getByRole("link", { name: individualResult.event })).toHaveAttribute("href", /meet_id=42/);

  for (const control of [
    page.getByPlaceholder("Search by swimmer name..."),
    page.getByPlaceholder("All Events"),
    page.getByLabel("Filter by meet"),
    page.getByRole("button", { name: "Show DQ" }),
    page.getByRole("button", { name: "View splits" }),
    page.getByRole("button", { name: "Previous" }),
    page.getByRole("button", { name: "2", exact: true }),
    page.getByRole("button", { name: "Next", exact: true }),
  ]) {
    const box = await control.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
});

test("Results active event controls are touch-sized and tablet layout does not overflow", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await stubFilters(page);
  await page.route("**/api/results/all**", (route) =>
    json(route, { data: [individualResult], pagination: { page: 1, limit: 50, total: 1, total_pages: 1 } }),
  );

  await page.goto(`/results?event=${encodeURIComponent(individualResult.event)}`);
  await expect(page.getByText(individualResult.event, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(768);

  const clearEvent = page.getByRole("button", { name: "Clear event filter" });
  const clearBox = await clearEvent.boundingBox();
  expect(clearBox?.width).toBeGreaterThanOrEqual(44);
  expect(clearBox?.height).toBeGreaterThanOrEqual(44);

  await page.getByPlaceholder("All Events").click();
  for (const choice of [
    page.getByRole("button", { name: "All Events", exact: true }),
    page.getByRole("button", { name: individualResult.event, exact: true }),
  ]) {
    expect((await choice.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  }
});

test("Results failures are announced", async ({ page }) => {
  await stubFilters(page);
  await page.route("**/api/results/all**", (route) => json(route, { detail: "Results unavailable" }, 503));
  await page.goto("/results");
  await expect(page.getByRole("alert").filter({ hasText: "Results unavailable" })).toBeVisible();
});

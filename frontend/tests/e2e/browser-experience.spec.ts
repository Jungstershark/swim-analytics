import { expect, test, type Page, type Route } from "@playwright/test";

const malformedSwimmerName = "Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston";

const pagination = (page = 1, total = 1) => ({
  page,
  limit: 24,
  total,
  total_pages: Math.max(1, Math.ceil(total / 24)),
});

const meet = {
  id: 42,
  name: "Singapore National Age Group Championships 2026",
  date: "2026-03-12",
  end_date: "2026-03-17",
  location: "OCBC Aquatic Centre",
};

const overview = {
  counts: {
    meets: 12,
    swimmers: 1842,
    individual_results: 24810,
    relay_results: 638,
    raw_documents: 91,
    source_references: 25448,
  },
  latest_meets: [meet],
  top_events: [],
  source_summary: {
    missing_individual_result_source_count: 0,
    missing_relay_result_source_count: 0,
  },
};

const swimmer = {
  id: 7,
  name: malformedSwimmerName,
  age: 15,
  team: "Singapore Swimming Club with an intentionally long imported team label",
  individual_result_count: 22,
  relay_result_count: 4,
  meet_count: 3,
  event_count: 8,
  latest_meet: meet,
  warning_count: 1,
  warnings: [{ type: "suspicious_swimmer_name", severity: "warning", message: "Imported name needs review" }],
};

const combinedResult = {
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
  legs: [],
  meet,
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubSharedApis(page: Page) {
  await page.route("**/api/browser/overview", (route) => json(route, overview));
  await page.route("**/api/browser/swimmers**", (route) =>
    json(route, { data: [swimmer], pagination: pagination() }),
  );
  await page.route("**/api/browser/meets**", (route) =>
    json(route, {
      data: [{ ...meet, event_group_count: 1, individual_result_count: 12, relay_result_count: 2, total_rows: 14 }],
      pagination: pagination(),
    }),
  );
  await page.route("**/api/meets**", (route) =>
    json(route, { data: [{ ...meet, result_count: 20, swimmer_count: 12 }], pagination: pagination() }),
  );
  await page.route("**/api/events**", (route) => json(route, { events: ["Girls 4x100m Freestyle Relay"] }));
  await page.route("**/api/results/all**", (route) =>
    json(route, { data: [combinedResult], pagination: { ...pagination(), limit: 50 } }),
  );
}

for (const width of [320, 390]) {
  test(`mobile shell fits ${width}px and exposes route-aware, touch-sized navigation`, async ({ page }) => {
    await page.setViewportSize({ width, height: 760 });
    await stubSharedApis(page);
    await page.goto("/swimmers");
    await expect(page.getByRole("heading", { name: malformedSwimmerName })).toBeVisible();

    const shell = page.getByRole("navigation", { name: "Primary" });
    await expect(shell.getByRole("link", { name: "Swimmers" })).toHaveAttribute("aria-current", "page");
    for (const label of ["Home", "Meets", "Swimmers", "Results"]) {
      const box = await shell.getByRole("link", { name: label, exact: true }).boundingBox();
      expect(box?.height).toBeGreaterThanOrEqual(44);
    }
    const actions = page.getByRole("button", { name: /actions|more/i });
    expect((await actions.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    await actions.click();
    await expect(page.getByRole("link", { name: "Upload" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sources" })).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
      primaryScrollWidth: document.querySelector('[aria-label="Primary"]')?.scrollWidth,
      primaryClientWidth: document.querySelector('[aria-label="Primary"]')?.clientWidth,
      headingScrollWidth: document.querySelector("h2")?.scrollWidth,
      headingClientWidth: document.querySelector("h2")?.clientWidth,
    }));
    expect(dimensions.document).toBe(dimensions.viewport);
    expect(dimensions.primaryScrollWidth).toBe(dimensions.primaryClientWidth);
    expect(dimensions.headingScrollWidth).toBe(dimensions.headingClientWidth);
  });
}

for (const width of [768, 1280]) {
  test(`desktop navigation fits ${width}px, includes Meets, and marks the current route`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await stubSharedApis(page);
    await page.goto("/meets");
    const desktop = page.getByRole("navigation", { name: "Desktop" });
    await expect(desktop.getByRole("link", { name: "Meets" })).toBeVisible();
    await expect(desktop.getByRole("link", { name: "Meets" })).toHaveAttribute("aria-current", "page");
    const dimensions = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    expect(dimensions[0]).toBe(dimensions[1]);
  });
}

test("dashboard uses the browser overview and links every metric into its dataset", async ({ page }) => {
  let overviewCalls = 0;
  await page.route("**/api/browser/overview", async (route) => {
    overviewCalls += 1;
    await json(route, overview);
  });
  await page.goto("/");

  await expect(page.getByRole("link", { name: /Swimmers 1,842/i })).toHaveAttribute("href", "/swimmers");
  await expect(page.getByRole("link", { name: /Meets 12/i })).toHaveAttribute("href", "/meets");
  await expect(page.getByRole("link", { name: /Results 25,448/i })).toHaveAttribute("href", "/results?row_type=all");
  await expect(page.getByRole("link", { name: /Relay results 638/i })).toHaveAttribute("href", "/results?row_type=relay");
  await expect(page.getByRole("link", { name: "View all" })).toHaveAttribute("href", "/meets");
  expect(overviewCalls).toBeGreaterThanOrEqual(1);
});

test("dashboard never presents failed totals as real zeroes", async ({ page }) => {
  await page.route("**/api/browser/overview", (route) => json(route, { detail: "Unavailable" }, 503));
  await page.goto("/");

  await expect(page.getByRole("alert").filter({ hasText: "Could not load dashboard data" })).toBeVisible();
  for (const label of ["Swimmers", "Meets", "Results", "Relay results"]) {
    const card = page.getByRole("link", { name: `${label} —`, exact: true });
    await expect(card).toBeVisible();
    await expect(card).not.toContainText("0");
  }
});

test("mobile action routes expose their current destination", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto("/upload");

  const shell = page.getByRole("navigation", { name: "Primary" });
  await expect(shell.getByRole("button", { name: "Actions" })).toHaveAttribute("aria-current", "page");
  await expect(shell.getByRole("link", { name: "Upload" })).toBeVisible();
  await expect(shell.getByRole("link", { name: "Upload" })).toHaveAttribute("aria-current", "page");
});

test("Meets index restores URL-owned filters on direct load and refresh", async ({ page }) => {
  const requests: URL[] = [];
  await page.route("**/api/browser/meets**", async (route) => {
    requests.push(new URL(route.request().url()));
    await json(route, {
      data: [{ ...meet, event_group_count: 48, individual_result_count: 2100, relay_result_count: 72, total_rows: 2172 }],
      pagination: { page: 2, limit: 24, total: 30, total_pages: 2 },
    });
  });

  await page.goto("/meets?q=National&sort=name&order=asc&page=2");
  await expect(page.getByRole("heading", { name: "Meets" })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search meets" })).toHaveValue("National");
  await expect(page.getByLabel("Sort meets")).toHaveValue("name");
  await expect(page.getByLabel("Sort direction")).toHaveValue("asc");
  await expect(page.getByRole("link", { name: meet.name })).toHaveAttribute("href", "/meets/42");
  await expect(page.getByText("Page 2 of 2")).toBeVisible();

  for (const key of ["q", "sort", "order", "page"]) {
    expect(requests.at(-1)?.searchParams.get(key)).toBe(new URL(page.url()).searchParams.get(key));
  }
  await page.reload();
  await expect(page.getByRole("searchbox", { name: "Search meets" })).toHaveValue("National");
  expect(requests.length).toBeGreaterThanOrEqual(2);
});

test("Meets index has recoverable error and empty states", async ({ page }) => {
  let mode: "error" | "empty" = "error";
  await page.route("**/api/browser/meets**", (route) =>
    mode === "error"
      ? json(route, { detail: "Meet catalogue is unavailable" }, 503)
      : json(route, { data: [], pagination: { page: 1, limit: 24, total: 0, total_pages: 0 } }),
  );
  await page.goto("/meets");
  await expect(page.getByRole("alert").filter({ hasText: "Meet catalogue is unavailable" })).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("No meets match these filters")).toBeVisible();
});

test("Results reads row_type from the URL, exposes it, and serializes it to the API", async ({ page }) => {
  const resultRequests: URL[] = [];
  await stubSharedApis(page);
  await page.unroute("**/api/results/all**");
  await page.route("**/api/results/all**", async (route) => {
    resultRequests.push(new URL(route.request().url()));
    await json(route, { data: [combinedResult], pagination: { ...pagination(), limit: 50 } });
  });

  await page.goto("/results?row_type=relay");
  await expect(page.getByRole("button", { name: "Relay results" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => resultRequests.some((request) => request.searchParams.get("row_type") === "relay")).toBe(true);

  await page.getByRole("button", { name: "All results" }).click();
  await expect(page).toHaveURL(/row_type=all/);
  await expect.poll(() => resultRequests.at(-1)?.searchParams.get("row_type")).toBe("all");
});

test("meet breadcrumbs lead through the Meets index", async ({ page }) => {
  await page.route("**/api/browser/meets/42", (route) => json(route, {
    meet,
    event_groups: [],
    summary: { event_group_count: 0, individual_result_count: 0, relay_result_count: 0, total_rows: 0 },
    source_summary: { missing_source_count: 0 },
    warnings: [],
  }));
  await page.goto("/meets/42");
  const breadcrumbs = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(breadcrumbs.getByRole("link", { name: "Meets" })).toHaveAttribute("href", "/meets");
  await expect(breadcrumbs).toContainText(meet.name);
});

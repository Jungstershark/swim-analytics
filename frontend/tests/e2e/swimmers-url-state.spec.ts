import { expect, test, type Page, type Route } from "@playwright/test";

const malformedSwimmerName = "Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston";

const swimmer = {
  id: 7,
  name: malformedSwimmerName,
  age: 15,
  team: "Singapore Swimming Club with an intentionally long imported team label",
  individual_result_count: 22,
  relay_result_count: 4,
  meet_count: 3,
  event_count: 8,
  latest_meet: {
    id: 42,
    name: "Singapore National Age Group Championships 2026",
    date: "2026-03-12",
    end_date: "2026-03-17",
    location: "OCBC Aquatic Centre",
  },
  warning_count: 1,
  warnings: [
    {
      type: "suspicious_swimmer_name",
      severity: "warning",
      message: "Imported name needs review",
    },
  ],
};

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function collectBrowserErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

function expectUrlApiParity(pageUrl: string, requestUrl: URL) {
  const browserUrl = new URL(pageUrl);
  for (const key of ["q", "team", "has_warnings", "page", "sort", "order"]) {
    expect(requestUrl.searchParams.get(key), `${key} should match the browser URL`).toBe(
      browserUrl.searchParams.get(key),
    );
  }
}

test("Swimmers restores URL-owned catalogue state across refresh and history without mobile overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  const browserErrors = collectBrowserErrors(page);
  const requests: URL[] = [];

  await page.route("**/api/browser/swimmers**", async (route) => {
    const requestUrl = new URL(route.request().url());
    requests.push(requestUrl);
    const requestedPage = Number(requestUrl.searchParams.get("page") || "1");
    await json(route, {
      data: [swimmer],
      pagination: { page: requestedPage, limit: 50, total: 51, total_pages: 2 },
    });
  });

  await page.goto(
    "/swimmers?q=Abdul%20Khair&team=Singapore%20Swimming%20Club&has_warnings=true&page=2&sort=latest_meet&order=desc",
  );

  await expect(page.getByRole("searchbox", { name: "Search swimmers by name" })).toHaveValue("Abdul Khair");
  await expect(page.getByRole("textbox", { name: "Filter swimmers by team or club" })).toHaveValue(
    "Singapore Swimming Club",
  );
  await expect(page.getByRole("button", { name: "Toggle swimmers with data-quality warnings only" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Sort swimmers")).toHaveValue("latest_meet");
  await expect(page.getByLabel("Sort swimmers").getByRole("option", { name: "Sort by individual swims" })).toHaveCount(1);
  await expect(page.getByLabel("Sort direction")).toHaveValue("desc");
  await expect(page.getByText("Page 2 of 2")).toBeVisible();

  const swimmerHeading = page.getByRole("heading", { name: malformedSwimmerName, exact: true });
  await expect(swimmerHeading).toBeVisible();
  await expect.poll(() => requests.length).toBeGreaterThan(0);
  expectUrlApiParity(page.url(), requests.at(-1)!);
  expect(requests.at(-1)!.searchParams.get("limit")).toBe("50");

  const controls = [
    page.getByRole("searchbox", { name: "Search swimmers by name" }),
    page.getByRole("textbox", { name: "Filter swimmers by team or club" }),
    page.getByRole("button", { name: "Toggle swimmers with data-quality warnings only" }),
    page.getByLabel("Sort swimmers"),
    page.getByLabel("Sort direction"),
    page.getByRole("button", { name: "Previous" }),
    page.getByRole("button", { name: "Next", exact: true }),
  ];
  for (const control of controls) {
    expect((await control.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  }

  const containment = await page.evaluate(() => {
    const heading = Array.from(document.querySelectorAll("h2")).find(
      (element) => element.textContent === "Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston",
    );
    const box = heading?.getBoundingClientRect();
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      headingRight: box?.right ?? Number.POSITIVE_INFINITY,
      headingText: heading?.textContent,
    };
  });
  expect(containment.documentWidth).toBe(containment.viewportWidth);
  expect(containment.headingRight).toBeLessThanOrEqual(containment.viewportWidth);
  expect(containment.headingText).toBe(malformedSwimmerName);

  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page).toHaveURL(/page=1/);
  await expect(page.getByText("Page 1 of 2")).toBeVisible();
  await expect.poll(() => requests.at(-1)?.searchParams.get("page")).toBe("1");
  expectUrlApiParity(page.url(), requests.at(-1)!);

  await page.goBack();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByText("Page 2 of 2")).toBeVisible();
  await expect(page.getByLabel("Sort swimmers")).toHaveValue("latest_meet");
  await expect(page.getByRole("button", { name: "Toggle swimmers with data-quality warnings only" })).toHaveAttribute("aria-pressed", "true");

  await page.goForward();
  await expect(page).toHaveURL(/page=1/);
  await page.reload();
  await expect(page.getByRole("searchbox", { name: "Search swimmers by name" })).toHaveValue("Abdul Khair");
  await expect(page.getByLabel("Sort direction")).toHaveValue("desc");
  await expect.poll(() => requests.at(-1)?.searchParams.get("page")).toBe("1");
  expectUrlApiParity(page.url(), requests.at(-1)!);
  expect(browserErrors).toEqual([]);
});

test("Swimmers ignores a delayed stale response after URL state changes", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const requests: URL[] = [];
  let releaseSlowResponse: () => void = () => {};
  let markSlowRequested: () => void = () => {};
  const slowResponseGate = new Promise<void>((resolve) => { releaseSlowResponse = resolve; });
  const slowRequested = new Promise<void>((resolve) => { markSlowRequested = resolve; });

  await page.route("**/api/browser/swimmers**", async (route) => {
    const requestUrl = new URL(route.request().url());
    requests.push(requestUrl);
    const query = requestUrl.searchParams.get("q");
    if (query === "slow") {
      markSlowRequested();
      await slowResponseGate;
      await json(route, {
        data: [{ ...swimmer, id: 70, name: "Slow stale swimmer" }],
        pagination: { page: 2, limit: 50, total: 51, total_pages: 2 },
      });
      return;
    }

    await json(route, {
      data: [{ ...swimmer, id: 71, name: "Fast current swimmer" }],
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    });
  });

  await page.goto("/swimmers?q=slow&team=Sharks&has_warnings=true&page=2&sort=team&order=desc");
  await slowRequested;
  await page.getByRole("searchbox", { name: "Search swimmers by name" }).fill("fast");

  await expect(page).toHaveURL(/q=fast/);
  await expect(page).toHaveURL(/page=1/);
  await expect(page.getByRole("heading", { name: "Fast current swimmer" })).toBeVisible();
  await expect.poll(() => requests.find((request) => request.searchParams.get("q") === "fast")?.toString()).toBeTruthy();
  const currentRequest = requests.findLast((request) => request.searchParams.get("q") === "fast")!;
  expectUrlApiParity(page.url(), currentRequest);

  releaseSlowResponse();
  await page.waitForTimeout(500);
  await expect(page.getByRole("heading", { name: "Fast current swimmer" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Slow stale swimmer" })).toHaveCount(0);
  await expect(page.getByRole("searchbox", { name: "Search swimmers by name" })).toHaveValue("fast");
  expect(browserErrors).toEqual([]);
});

test("Swimmers merges independently debounced name and team filters", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/api/browser/swimmers**", (route) =>
    json(route, {
      data: [{ ...swimmer, id: 72, name: "Merged state swimmer" }],
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    }),
  );

  await page.goto("/swimmers");
  await expect(page.getByRole("heading", { name: "Merged state swimmer" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search swimmers by name" }).fill("Alice");
  await page.getByRole("textbox", { name: "Filter swimmers by team or club" }).fill("Sharks");

  await expect.poll(() => {
    const params = new URL(page.url()).searchParams;
    return { q: params.get("q"), team: params.get("team") };
  }).toEqual({ q: "Alice", team: "Sharks" });
  expect(browserErrors).toEqual([]);
});

test("Swimmers merges rapid control changes into one current URL state", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const requests: URL[] = [];

  await page.route("**/api/browser/swimmers**", async (route) => {
    const requestUrl = new URL(route.request().url());
    requests.push(requestUrl);
    await json(route, {
      data: [{ ...swimmer, id: 72, name: "Merged state swimmer" }],
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    });
  });

  await page.goto("/swimmers?q=old&team=Sharks&has_warnings=true&page=2&sort=name&order=desc");
  await expect(page.getByRole("heading", { name: "Merged state swimmer" })).toBeVisible();

  await page.getByRole("searchbox", { name: "Search swimmers by name" }).fill("current");
  await page.getByLabel("Sort swimmers").selectOption("team");

  await expect(page).toHaveURL(/q=current/);
  await expect(page).toHaveURL(/sort=team/);
  await expect(page).toHaveURL(/page=1/);
  await expect.poll(() => requests.at(-1)?.searchParams.get("q")).toBe("current");
  expectUrlApiParity(page.url(), requests.at(-1)!);
  expect(browserErrors).toEqual([]);
});

test("Swimmers cancels a pending name debounce when Back restores history", async ({ page }) => {
  await page.route("**/api/browser/swimmers**", (route) =>
    json(route, {
      data: [{ ...swimmer, id: 73, name: "History swimmer" }],
      pagination: { page: 1, limit: 50, total: 1, total_pages: 1 },
    }),
  );

  await page.goto("/swimmers?q=before");
  await page.getByLabel("Sort swimmers").selectOption("team");
  await expect(page).toHaveURL(/sort=team/);
  await page.getByRole("searchbox", { name: "Search swimmers by name" }).fill("current");
  await page.goBack();

  await expect(page).toHaveURL(/q=before/);
  await expect(page).not.toHaveURL(/sort=team/);
  await page.waitForTimeout(500);
  await expect(page).toHaveURL(/q=before/);
  await expect(page).not.toHaveURL(/sort=team/);
  await expect(page.getByRole("searchbox", { name: "Search swimmers by name" })).toHaveValue("before");
});

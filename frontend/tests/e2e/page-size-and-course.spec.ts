import { expect, test, type Page, type Route } from "@playwright/test";

const meet = { id: 42, name: "National Championships", date: "2026-03-12", end_date: null, location: "Singapore" };

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

const result = {
  type: "individual" as const,
  id: 90,
  event: "Girls 100m Freestyle",
  time: "1:02.53",
  seed_time: null,
  placement: 2,
  is_dq: false,
  status: "finished",
  round: "Final",
  swim_date: "2026-03-14",
  qualifier: null,
  swimmer: { id: 7, name: "Tan, Alice", age: 15, team: "Sharks" },
  is_guest: false,
  team_name: null,
  relay_letter: null,
  is_exhibition: false,
  legs: [],
  meet,
};

function browserSwimmer(id = 7, name = "Tan, Alice") {
  return {
    id, name, age: 15, team: "Sharks", individual_result_count: 4, relay_result_count: 0,
    meet_count: 2, event_count: 2, latest_meet: meet, warning_count: 0, warnings: [],
  };
}

function eventDetail(limit: number) {
  return {
    event_group: { event_label: result.event, source_event_number: "12", total_rows: 80, rounds: ["Final"] },
    data: [{
      row_type: "individual", id: 90, event_label: result.event, time: result.time, placement: 2,
      status: "finished", is_dq: false, round: "Final", is_guest: false, swimmer: result.swimmer,
      team_name: null, relay_letter: null, legs: [], warnings: [], source: { document_sha256: "abc" },
    }],
    pagination: { page: 2, limit, total: 80, total_pages: Math.ceil(80 / limit) }, warnings: [],
  };
}

async function stubResultsFilters(page: Page) {
  await page.route("**/api/meets**", (route) => json(route, { data: [{ ...meet, result_count: 4, swimmer_count: 1 }], pagination: { page: 1, limit: 100, total: 1, total_pages: 1 } }));
  await page.route("**/api/events**", (route) => json(route, { events: [result.event] }));
}

test("Results owns supported page size in the URL, resets page, and omits the default", async ({ page }) => {
  const requests: URL[] = [];
  await stubResultsFilters(page);
  await page.route("**/api/results/all**", async (route) => {
    const request = new URL(route.request().url());
    requests.push(request);
    const limit = Number(request.searchParams.get("limit"));
    await json(route, { data: [result], pagination: { page: Number(request.searchParams.get("page") || 1), limit, total: 120, total_pages: Math.ceil(120 / limit) } });
  });

  await page.goto("/results?page=2&limit=25");
  const selector = page.getByLabel("Results per page");
  await expect(selector).toHaveValue("25");
  await expect.poll(() => requests.at(-1)?.searchParams.get("limit")).toBe("25");
  await selector.selectOption("100");
  await expect(page).toHaveURL(/limit=100/);
  await expect(page).not.toHaveURL(/[?&]page=/);
  await expect.poll(() => requests.at(-1)?.searchParams.get("limit")).toBe("100");
  await selector.selectOption("50");
  await expect(page).not.toHaveURL(/[?&]limit=/);
  expect((await selector.boundingBox())?.height).toBeGreaterThanOrEqual(44);

  await page.goto("/results?limit=12");
  await expect(page).not.toHaveURL(/[?&]limit=/);
  await expect.poll(() => requests.at(-1)?.searchParams.get("limit")).toBe("50");

  await page.goto("/results?row_type=relay");
  await page.goto("/results?row_type=individual&limit=12");
  await expect(page).toHaveURL(/row_type=individual/);
  await expect(page).not.toHaveURL(/[?&]limit=/);
  await page.goBack();
  await expect(page).toHaveURL(/row_type=relay/);
});

test("Swimmers and Meets serialize supported page size, reset pages, and canonicalize invalid limits", async ({ page }) => {
  const swimmerRequests: URL[] = [];
  const meetRequests: URL[] = [];
  await page.route("**/api/browser/swimmers**", async (route) => {
    const request = new URL(route.request().url());
    swimmerRequests.push(request);
    const limit = Number(request.searchParams.get("limit"));
    await json(route, { data: [browserSwimmer()], pagination: { page: Number(request.searchParams.get("page") || 1), limit, total: 120, total_pages: Math.ceil(120 / limit) } });
  });
  await page.route("**/api/browser/meets**", async (route) => {
    const request = new URL(route.request().url());
    meetRequests.push(request);
    const limit = Number(request.searchParams.get("limit"));
    await json(route, { data: [{ ...meet, event_group_count: 1, individual_result_count: 4, relay_result_count: 0, total_rows: 4 }], pagination: { page: Number(request.searchParams.get("page") || 1), limit, total: 120, total_pages: Math.ceil(120 / limit) } });
  });

  await page.goto("/swimmers?page=2&limit=25");
  await page.getByLabel("Swimmers per page").selectOption("100");
  await expect(page).toHaveURL(/limit=100/);
  await expect(page).not.toHaveURL(/[?&]page=/);
  await expect.poll(() => swimmerRequests.at(-1)?.searchParams.get("limit")).toBe("100");
  await page.goto("/swimmers?limit=999");
  await expect(page).not.toHaveURL(/[?&]limit=/);
  await expect.poll(() => swimmerRequests.at(-1)?.searchParams.get("limit")).toBe("50");

  await page.goto("/meets?page=2&limit=25");
  await page.getByLabel("Meets per page").selectOption("100");
  await expect(page).toHaveURL(/limit=100/);
  await expect(page).not.toHaveURL(/[?&]page=/);
  await expect.poll(() => meetRequests.at(-1)?.searchParams.get("limit")).toBe("100");
  await page.goto("/meets?limit=nope");
  await expect(page).not.toHaveURL(/[?&]limit=/);
  await expect.poll(() => meetRequests.at(-1)?.searchParams.get("limit")).toBe("50");
});

test("Meet event results support URL-owned page size with canonical invalid limits", async ({ page }) => {
  const requests: URL[] = [];
  await page.route("**/api/browser/events**", async (route) => {
    const request = new URL(route.request().url());
    requests.push(request);
    await json(route, eventDetail(Number(request.searchParams.get("limit"))));
  });

  await page.goto("/meets/42/events/freestyle?page=2&limit=25");
  await page.getByLabel("Event results per page").selectOption("100");
  await expect(page).toHaveURL(/limit=100/);
  await expect(page).not.toHaveURL(/[?&]page=/);
  await expect.poll(() => requests.at(-1)?.searchParams.get("limit")).toBe("100");
  await page.goto("/meets/42/events/freestyle?limit=9");
  await expect(page).not.toHaveURL(/[?&]limit=/);
  await expect.poll(() => requests.at(-1)?.searchParams.get("limit")).toBe("50");
});

test("Swimmer all-courses view keeps course headings and PBs separate, with URL-owned course selection", async ({ page }) => {
  const lcmEvent = { course: "LCM" as const, distance_m: 100, stroke: "Freestyle", event: "100m Freestyle", canonical_event_key: "100-free", normalization_status: "normalized", source_event_labels: ["100 Free"], performance_count: 2, finished_performance_count: 2, fastest_recorded: { ...result, id: 10, time: "1:00.00", source: { document_sha256: "a" }, warnings: [], splits: [] }, split_coverage: { available: 0, total: 2 }, performances: [] };
  const scmEvent = { ...lcmEvent, course: "SCM" as const, fastest_recorded: { ...lcmEvent.fastest_recorded, id: 11, time: "0:58.00" } };
  await page.route("**/api/browser/swimmers/7", (route) => json(route, {
    swimmer: result.swimmer,
    stats: { individual_result_count: 4, relay_result_count: 0, meet_count: 2, event_count: 2, warning_count: 0 },
    personal_bests: [], event_history: [],
    course_history: [{ course: "LCM", event_count: 1, events: [lcmEvent] }, { course: "SCM", event_count: 1, events: [scmEvent] }],
    relay_history: [], warnings: [],
  }));

  await page.goto("/swimmers/7?course=invalid");
  await expect(page).not.toHaveURL(/[?&]course=/);
  await expect(page.getByRole("button", { name: /All courses/i })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "LCM", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "SCM", exact: true })).toBeVisible();
  await expect(page.getByText("1:00.00")).toBeVisible();
  await expect(page.getByText("0:58.00")).toBeVisible();

  await page.getByRole("button", { name: /SCM/i }).click();
  await expect(page).toHaveURL(/course=SCM/);
  await expect(page.getByRole("heading", { name: "LCM", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /All courses/i }).click();
  await expect(page).not.toHaveURL(/[?&]course=/);
  await page.goto("/swimmers/7?course=unknown");
  await expect(page).toHaveURL(/course=unknown/);
  await expect(page.getByRole("button", { name: /All courses/i })).toHaveAttribute("aria-pressed", "false");
});

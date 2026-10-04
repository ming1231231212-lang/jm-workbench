import test from "node:test";
import assert from "node:assert/strict";
import {
  savedDensity,
  ViewRequests,
  routeIcons,
} from "../jm_workbench/web/static/workspace.js";
import { pages } from "../jm_workbench/web/static/views.js";

test("a slow previous page never replaces the current page", async () => {
  const requests = new ViewRequests();
  let finishPrevious, displayed;
  const previous = requests.begin();
  const pending = new Promise((resolve) => (finishPrevious = resolve)).then(
    () => {
      if (previous()) displayed = "old";
    },
  );
  const current = requests.begin();
  if (current()) displayed = "current";
  finishPrevious();
  await pending;
  assert.equal(displayed, "current");
});
test("same-route refresh also discards older responses", () => {
  const requests = new ViewRequests();
  const older = requests.begin(),
    newer = requests.begin();
  assert.equal(older(), false);
  assert.equal(newer(), true);
});
test("density migrates community preference but honors an explicit global choice", () => {
  const values = new Map([["jm-community-density", "compact"]]);
  const storage = { getItem: (key) => values.get(key) ?? null };
  assert.equal(savedDensity(storage), true);
  values.set("jm-workspace-density", "comfortable");
  assert.equal(savedDensity(storage), false);
});
test("blocked browser storage does not prevent opening the workspace", () => {
  assert.equal(
    savedDensity({
      getItem() {
        throw Error("storage unavailable");
      },
    }),
    false,
  );
});
test("all primary routes use the same local icon library", () => {
  assert.deepEqual(
    Object.keys(routeIcons),
    pages.filter((p) => !p[3]).map((p) => p[0]),
  );
});

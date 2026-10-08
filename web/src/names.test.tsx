// A unit has one name, `change/N`, and every place it appears shows that name.
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import { recordedApi } from "./test/api";
import { unitPath } from "./unitName";

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  recordedApi();
});

describe("a unit's route", () => {
  it("is /units/<change>/<n> and holds nothing else", () => {
    expect(unitPath("feature/7")).toBe("/units/feature/7");
    expect(unitPath("needs-gate-started-units/1")).toBe("/units/needs-gate-started-units/1");
  });

  it("opens the page of the unit named in the address", async () => {
    open("/units/feature/7");

    expect(await screen.findByRole("heading", { name: "feature/7" })).toBeVisible();
  });

  it("is what a link to the unit points at, with the name as its text", async () => {
    open("/");

    const link = await screen.findByRole("link", { name: /^feature\/6\b/ });
    expect(link).toHaveAttribute("href", "/units/feature/6");
    expect(link).toHaveTextContent("feature/6");
  });

  it("is what a dependency or merge gate links to", async () => {
    open("/units/feature/3");

    const gate = await screen.findByRole("link", { name: "feature/2" });
    expect(gate).toHaveAttribute("href", "/units/feature/2");
  });

  it("shows no generated identifier in any address on the page", async () => {
    open("/");
    await screen.findByRole("link", { name: /^feature\/1\b/ });

    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href") ?? "");
    for (const href of hrefs) {
      expect(href).toMatch(/^\/(units\/[\w.-]+\/\d+|usage|metrics)?$/);
    }
    expect(hrefs.some((href) => href.startsWith("/units/"))).toBe(true);
  });
});

describe("the same name everywhere", () => {
  it("is the title on the page and the text of the link that leads to it", async () => {
    open("/");
    const link = await screen.findByRole("link", { name: /^feature\/2\b/ });
    const href = link.getAttribute("href") as string;
    cleanup();

    open(href);

    expect(await screen.findByRole("heading", { name: "feature/2" })).toBeVisible();
  });

  it("is the unit key in a usage row, linking to the unit's page", async () => {
    open("/usage");

    const link = await screen.findByRole("link", { name: "add-marker/1" });
    expect(link).toHaveAttribute("href", "/units/add-marker/1");
  });
});

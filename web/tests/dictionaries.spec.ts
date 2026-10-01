import { cell, expect, go, menu, modal, orderItem, panel, PROJECT, ruleCard, test, toast, TRAINING } from "./fixtures";
import type { Page } from "@playwright/test";

/* Справочники (подразделения, атрибуты) и замечания к данным. */

const departmentRow = (page: Page, id: string) =>
  page.locator("#tab-departments tr").filter({ has: page.locator(".mono", { hasText: id }) });
const targetRow = (page: Page, name: string) => page.locator("#tab-targets tr").filter({ hasText: name });

test("подразделения: создание, двойник идентификатора, правка", async ({ app }) => {
  await go(app, "Подразделения");
  await expect(departmentRow(app, "UCT")).toContainText("R-1.1");
  await expect(departmentRow(app, "FIN")).toContainText("R-2.4 · кандидат");

  await app.locator("#tab-departments").getByRole("button", { name: "+ Подразделение" }).click();
  await modal(app).getByLabel("Идентификатор").fill("UCT");
  await modal(app).getByLabel("Название").fill("Дубль");
  await modal(app).getByRole("button", { name: "Создать" }).click();
  await expect(toast(app, "уже существует")).toBeVisible();

  await modal(app).getByLabel("Идентификатор").fill("HR");
  await modal(app).getByLabel("Название").fill("Управление персоналом");
  await modal(app).getByRole("button", { name: "Создать" }).click();
  await expect(toast(app, "Подразделение создано")).toBeVisible();
  await expect(departmentRow(app, "HR")).toContainText("Управление персоналом");

  await menu(departmentRow(app, "HR"), "Изменить");
  await modal(app).getByLabel("Название").fill("Служба персонала");
  await modal(app).getByRole("button", { name: "Сохранить" }).click();
  await expect(departmentRow(app, "HR")).toContainText("Служба персонала");

  // Новое подразделение сразу появляется столбцом матрицы.
  await go(app, "Правила");
  await expect(cell(app, TRAINING, "Служба персонала")).toHaveAttribute("data-state", "applies");
  await expect(cell(app, PROJECT, "Служба персонала")).toHaveAttribute("data-state", "off");
});

test("подразделение, задающее область действия правил, удалить нельзя", async ({ app }) => {
  await go(app, "Подразделения");
  await menu(departmentRow(app, "UCT"), "Удалить");
  await app.getByRole("dialog").getByRole("button", { name: "Удалить" }).click();
  await expect(toast(app, "задаёт область действия правил: R-1.1")).toBeVisible();
  await expect(departmentRow(app, "UCT")).toBeVisible();
});

test("архивное подразделение уходит из проверки и матрицы", async ({ app }) => {
  await go(app, "Подразделения");
  await menu(departmentRow(app, "FIN"), "В архив");
  await expect(departmentRow(app, "FIN")).toHaveCount(0);
  await go(app, "Проверка цели");
  await expect(app.locator("#departmentInput option")).toHaveText(["Подразделение не указано", "АГД", "УЦТ"]);
  await go(app, "Правила");
  await expect(app.locator("#tab-rules thead th")).toHaveText(["Правило", "АГД", "УЦТ"]);
});

test("архивирование используемого атрибута спрашивает подтверждение", async ({ app }) => {
  await go(app, "Атрибуты");
  const row = targetRow(app, "срок_исполнения");
  await menu(row, "В архив");
  await expect(app.getByRole("dialog")).toContainText("R-2.4");
  await app.getByRole("button", { name: "Отмена" }).click();
  await expect(row).toBeVisible();
  await menu(row, "В архив");
  await app.getByRole("button", { name: "Всё равно в архив" }).click();
  await expect(row).toHaveCount(0);
});

test("двойника атрибута по написанию создать нельзя", async ({ app }) => {
  await go(app, "Атрибуты");
  await app.locator("#tab-targets").getByRole("button", { name: "+ Атрибут" }).click();
  await modal(app).getByLabel("Имя").fill("Срок исполнения");
  await modal(app).getByLabel("Описание для модели").fill("дата");
  await modal(app).getByRole("button", { name: "Создать" }).click();
  await expect(toast(app, "уже есть")).toBeVisible();
  await expect(modal(app).locator(".modal")).toBeVisible();
});

test("значок замечаний показывает число ошибок", async ({ app }) => {
  await expect(app.getByRole("tab", { name: /Замечания/ }).locator(".n.err")).toHaveText("2");
});

test("из замечаний — к атрибуту, правилу и приказу", async ({ app }) => {
  await go(app, /Замечания/);
  await expect(app.getByText("Граф не готов к проверкам")).toBeVisible();

  await app.locator(".issue").filter({ hasText: "Атрибуты без описания" }).getByRole("button", { name: "Показать" }).click();
  await expect(app.getByRole("tab", { name: "Атрибуты" })).toHaveAttribute("aria-selected", "true");
  await expect(targetRow(app, "обучение")).toHaveClass(/flash/);

  await go(app, /Замечания/);
  const noKeys = app.locator(".issue").filter({ hasText: "Узлы без идентификатора" });
  await noKeys.locator(".item").filter({ hasText: "Rule" }).getByRole("button", { name: "Показать" }).click();
  await expect(app.getByRole("tab", { name: "Приказы" })).toHaveAttribute("aria-selected", "true");
  await expect(orderItem(app, "ПР-02")).toHaveAttribute("aria-selected", "true");
  await expect(ruleCard(app, TRAINING)).toHaveClass(/flash/);
  await expect(panel(app)).toContainText("Приказ ПР-02, пункт 3.1");

  await go(app, /Замечания/);
  const candidates = app.locator(".issue").filter({ hasText: "Исключения-кандидаты ждут утверждения" });
  await expect(candidates.getByText("Справочно")).toBeVisible();
  await candidates.getByRole("button", { name: "Показать" }).click();
  await expect(panel(app).locator('[data-exception="FIN"]')).toContainText("кандидат");
});

test("автопочинка идентификаторов", async ({ app }) => {
  await go(app, /Замечания/);
  await app.getByRole("button", { name: "Проставить идентификаторы" }).click();
  await app.getByRole("dialog").getByRole("button", { name: "Проставить" }).click();
  await expect(toast(app, "Проставлено: приказов 1, пунктов 1, правил 1")).toBeVisible();
  await expect(app.locator(".issue").filter({ hasText: "Узлы без идентификатора" })).toHaveCount(0);
  await go(app, "Приказы");
  await orderItem(app, "ПР-02").click();
  await expect(app.locator("#tab-orders").getByText("нет orderId")).toHaveCount(0);
});

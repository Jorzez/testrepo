import { expect, menu, openClause, test, toast } from "./fixtures";
import type { Page } from "@playwright/test";

/* Разграничение правил по подразделениям. В данных фейкового API:
     R-1.1 (нужен проект) действует только в УЦТ и АГД;
     R-2.4 (нужен срок) не применяется в АГД по «ПР-01 п. 2.5»,
     а для финансового управления исключение — пока кандидат. */

const rule = (page: Page, text: string) => page.locator(".rule").filter({ hasText: text });
const departmentRow = (page: Page, id: string) =>
  page.locator("#tab-departments tr").filter({ has: page.locator(".mono", { hasText: id }) });

async function check(page: Page, goal: string, department: string | null) {
  await page.getByRole("tab", { name: "Проверка цели" }).click();
  await page.getByLabel("Формулировка цели").fill(goal);
  await page.getByLabel("Подразделение").selectOption(department ?? "");
  await page.getByRole("button", { name: "Проверить" }).click();
  return page.locator("#checkResult");
}

test("правило показывает область действия", async ({ app }) => {
  await openClause(app, "ПР-01", "1.1");
  const project = rule(app, "Цель обязана содержать упоминание проекта");
  await expect(project.getByText("только в:")).toBeVisible();
  await expect(project.locator(".chip", { hasText: "УЦТ" })).toBeVisible();
  await expect(project.locator(".chip", { hasText: "АГД" })).toBeVisible();

  await app.locator(".clause-head").filter({ hasText: "2.4" }).click();
  const deadline = rule(app, "Цель обязана содержать конкретный срок исполнения");
  await expect(deadline.locator(".chip", { hasText: "АГД · ПР-01 п. 2.5" })).toBeVisible();
  await expect(deadline.locator(".chip", { hasText: "Финансовое управление · кандидат" })).toBeVisible();
});

test("правило без связей действует для всех", async ({ app }) => {
  await openClause(app, "ПР-02", "3.1");
  await expect(rule(app, "Обучение само по себе").getByText("для всех подразделений")).toBeVisible();
});

test("правило «только в» не применяется к другому подразделению", async ({ app }) => {
  const goal = "Снизить долю просроченных заявок до 5% к 31.12.2025";
  let result = await check(app, goal, "FIN");
  await expect(result.getByText("Нарушений нет")).toBeVisible();
  await expect(result.locator(".chip", { hasText: "Финансовое управление" })).toBeVisible();

  result = await check(app, goal, "UCT");
  await expect(result.getByText("Найдены нарушения")).toBeVisible();
  await expect(result.locator(".violation")).toContainText("ПР-01 1.1");
});

test("без подразделения применяются все правила, причина — в заметках", async ({ app }) => {
  const result = await check(app, "Улучшить работу с заявками", null);
  await expect(result.getByText("подразделение: не определено")).toBeVisible();
  await expect(result.getByText(/Подразделение не передано: применены все правила/)).toBeVisible();
  await expect(result.locator(".violation")).toHaveCount(2);
  await expect(result.locator(".exemption")).toHaveCount(0);
});

test("утверждённое исключение снимает нарушение и показывает основание", async ({ app }) => {
  const result = await check(app, "В рамках проекта «Альфа» улучшить работу с заявками", "AGD");
  await expect(result.getByText("Нарушений нет")).toBeVisible();
  const exemption = result.locator(".exemption");
  await expect(exemption).toContainText("Не применяется в подразделении");
  await expect(exemption).toContainText("ПР-01 2.4");
  await expect(exemption).toContainText("Основание: ПР-01 п. 2.5");
});

test("исключение-кандидат в вердикте не участвует", async ({ app }) => {
  const result = await check(app, "Улучшить работу с заявками", "FIN");
  await expect(result.getByText("Найдены нарушения")).toBeVisible();
  const violation = result.locator(".violation");
  await expect(violation).toHaveCount(1);
  await expect(violation).toContainText("ПР-01 2.4");
  await expect(violation.getByText("есть исключение-кандидат — не утверждено")).toBeVisible();
  await expect(result.locator(".exemption")).toHaveCount(0);
});

test("утверждение кандидата: нужно основание, после — исключение действует", async ({ app }) => {
  await openClause(app, "ПР-01", "2.4");
  const deadline = rule(app, "Цель обязана содержать конкретный срок исполнения");
  await menu(deadline, "Подразделения");

  const row = app.locator('.scope-row[data-exception="FIN"]');
  await row.getByLabel("Статус исключения").selectOption("active");
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "нужно основание")).toBeVisible();

  await row.getByLabel("Основание").fill("ПР-01 п. 2.6");
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "Область действия обновлена")).toBeVisible();
  await expect(deadline.locator(".chip", { hasText: "Финансовое управление · ПР-01 п. 2.6" })).toBeVisible();

  const result = await check(app, "Улучшить работу с заявками", "FIN");
  await expect(result.getByText("Нарушений нет")).toBeVisible();
  await expect(result.locator(".exemption")).toContainText("Основание: ПР-01 п. 2.6");
});

test("редактор области действия: только-в и исключения не пересекаются", async ({ app }) => {
  await openClause(app, "ПР-02", "3.1");
  const training = rule(app, "Обучение само по себе");
  await training.getByRole("button", { name: "подразделения…" }).click();

  await app.locator("#scopeOnly").getByLabel(/УЦТ/).check();
  await app.getByRole("button", { name: "+ Исключение" }).click();
  const row = app.locator(".scope-row");
  // УЦТ уже отмечен в «только в» — в исключения его выбрать нельзя.
  await expect(row.getByLabel("Подразделение").locator("option")).toHaveText([
    "АГД · AGD", "Финансовое управление · FIN"]);
  await expect(app.locator("#scopeOnly").getByLabel(/АГД/)).toBeDisabled();
  await row.getByLabel("Примечание").fill("договорённость отдела");
  await app.getByRole("button", { name: "Сохранить" }).click();

  await expect(training.locator(".chip", { hasText: "УЦТ" })).toBeVisible();
  await expect(training.locator(".chip", { hasText: "АГД · кандидат" })).toBeVisible();
});

test("подразделения: создание, двойник идентификатора, правка", async ({ app }) => {
  await app.getByRole("tab", { name: "Подразделения" }).click();
  await expect(departmentRow(app, "UCT")).toContainText("R-1.1");
  await expect(departmentRow(app, "FIN")).toContainText("R-2.4 · кандидат");

  const create = app.locator("#tab-departments").getByRole("button", { name: "Создать" });
  await create.click();
  await app.getByLabel("Идентификатор").fill("UCT");
  await app.getByLabel("Название").fill("Дубль");
  await app.getByRole("button", { name: "Создать" }).last().click();
  await expect(toast(app, "уже существует")).toBeVisible();

  await app.getByLabel("Идентификатор").fill("HR");
  await app.getByLabel("Название").fill("Управление персоналом");
  await app.getByRole("button", { name: "Создать" }).last().click();
  await expect(toast(app, "Подразделение создано")).toBeVisible();
  await expect(departmentRow(app, "HR")).toContainText("Управление персоналом");

  await menu(departmentRow(app, "HR"), "Изменить");
  await app.getByLabel("Название").fill("Служба персонала");
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(departmentRow(app, "HR")).toContainText("Служба персонала");
});

test("подразделение, задающее область действия правил, удалить нельзя", async ({ app }) => {
  await app.getByRole("tab", { name: "Подразделения" }).click();
  await menu(departmentRow(app, "UCT"), "Удалить");
  await app.getByRole("dialog").getByRole("button", { name: "Удалить" }).click();
  await expect(toast(app, "задаёт область действия правил: R-1.1")).toBeVisible();
  await expect(departmentRow(app, "UCT")).toBeVisible();
});

test("архивное подразделение: правила применяются все", async ({ app }) => {
  await app.getByRole("tab", { name: "Подразделения" }).click();
  await menu(departmentRow(app, "FIN"), "В архив");
  await expect(departmentRow(app, "FIN")).toBeHidden();
  await app.getByRole("tab", { name: "Проверка цели" }).click();
  await expect(app.getByLabel("Подразделение").locator("option")).toHaveText([
    "не указано — применяются все правила", "АГД · AGD", "УЦТ · UCT"]);
});

test("диагностика показывает кандидатов и ведёт к правилу", async ({ app }) => {
  await app.getByRole("tab", { name: /Диагностика/ }).click();
  const issue = app.locator(".issue").filter({ hasText: "Исключения-кандидаты ждут утверждения" });
  await expect(issue.getByText("Справочно")).toBeVisible();
  await issue.getByRole("button", { name: "Показать" }).click();
  await expect(rule(app, "Цель обязана содержать конкретный срок исполнения")).toHaveClass(/flash/);
});

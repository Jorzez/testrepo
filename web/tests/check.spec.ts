import { check, expect, go, isApi, test, toast } from "./fixtures";

const GOAL = "Снизить долю просроченных заявок до 5% к 31.12.2025";

test("ответ проверки объясняет, что не так и как исправить", async ({ app }) => {
  const result = await check(app, GOAL);
  await expect(result.getByText("Нужно доработать")).toBeVisible();
  await expect(result.getByText("не выполнено правил: 1 из 3")).toBeVisible();
  const violation = result.locator(".violation");
  await expect(violation).toContainText("Цель обязана содержать упоминание проекта");
  await expect(violation).toContainText("Приказ ПР-01, пункт 1.1");
  await expect(violation).toContainText("Как исправить:");
  await expect(violation).toContainText("Пример: «В рамках проекта «Альфа»");

  // Результат не теряется при переходе между разделами.
  await go(app, "Атрибуты");
  await go(app, "Проверка цели");
  await expect(result.getByText("Нужно доработать")).toBeVisible();
});

test("без подразделения применяются все правила, причина — в заметках", async ({ app }) => {
  const result = await check(app, "Улучшить работу с заявками");
  await expect(result.getByText("подразделение: не определено")).toBeVisible();
  await expect(result.getByText(/Подразделение не передано: применены все правила/)).toBeVisible();
  await expect(result.locator(".violation")).toHaveCount(2);
  await expect(result.locator(".exemption")).toHaveCount(0);
});

test("правило «только в» не применяется к другому подразделению", async ({ app }) => {
  let result = await check(app, GOAL, "FIN");
  await expect(result.getByText("Нарушений нет")).toBeVisible();
  await expect(result.locator(".chip", { hasText: "Финансовое управление" })).toBeVisible();
  await expect(app.getByText("правил: 2 · не для этого подразделения: 1")).toBeVisible();

  result = await check(app, GOAL, "UCT");
  await expect(result.getByText("Нужно доработать")).toBeVisible();
  await expect(result.locator(".violation")).toContainText("пункт 1.1");
});

test("утверждённое исключение снимает нарушение и показывает основание", async ({ app }) => {
  const result = await check(app, "В рамках проекта «Альфа» улучшить работу с заявками", "AGD");
  await expect(result.getByText("Нарушений нет")).toBeVisible();
  const exemption = result.locator(".exemption");
  await expect(exemption).toContainText("не применяется в подразделении");
  await expect(exemption).toContainText("пункт 2.4");
  await expect(exemption).toContainText("Основание: ПР-01 п. 2.5");
  await expect(app.locator("#tab-check .checkline").filter({ hasText: "срок" }))
    .toContainText("не применяется (ПР-01 п. 2.5)");
});

test("исключение-кандидат в вердикте не участвует", async ({ app }) => {
  const result = await check(app, "Улучшить работу с заявками", "FIN");
  await expect(result.getByText("Нужно доработать")).toBeVisible();
  const violation = result.locator(".violation");
  await expect(violation).toHaveCount(1);
  await expect(violation).toContainText("пункт 2.4");
  await expect(violation.getByText("есть исключение-кандидат — не утверждено")).toBeVisible();
  await expect(result.locator(".exemption")).toHaveCount(0);
});

test("главный экран показывает, что ждёт решения", async ({ app }) => {
  const todo = app.locator("#tab-check .todo");
  await expect(todo.filter({ hasText: "Исключений ждут утверждения: 1" })).toBeVisible();
  await todo.filter({ hasText: "Замечаний к данным: 2" }).getByRole("button", { name: "Открыть" }).click();
  await expect(app.getByRole("tab", { name: /Замечания/ })).toHaveAttribute("aria-selected", "true");
});

test("пустая цель не отправляется", async ({ app }) => {
  await app.locator("#tab-check").getByRole("button", { name: "Проверить" }).click();
  await expect(toast(app, "Введите формулировку цели")).toBeVisible();
});

test("недоступный API виден в боковой панели", async ({ page }) => {
  // Сессия есть, а каталог не отвечает: интерфейс открыт, но данных нет.
  await page.route(isApi, (route) => new URL(route.request().url()).pathname === "/api/auth/me"
    ? route.fulfill({ json: { login: "admin", role: "admin", displayName: null } })
    : route.abort());
  await page.goto("/");
  await expect(page.locator(".side").getByText("API недоступен")).toBeVisible();
  await expect(toast(page, "Не удалось получить данные")).toBeVisible();
});

test("без связи с сервером формы входа нет — только повтор", async ({ page }) => {
  await page.route(isApi, (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText("Не удалось связаться с сервером")).toBeVisible();
  await expect(page.getByLabel("Пароль")).toHaveCount(0);
});

test("путь проверки показывается на графе", async ({ app }) => {
  const result = await check(app, "Пройти обучение по охране труда до 31.12.2025", "AGD");
  await result.getByRole("button", { name: "Показать на графе" }).click();

  const graph = app.locator("#tab-graph");
  await expect(graph.locator(".node.goal")).toBeVisible();
  // Найденный атрибут, нарушенное правило с его пунктом и приказом, ненайденный обязательный атрибут.
  await expect(graph.locator(".node.traced.ok")).toContainText(["срок_исполнения"]);
  await expect(graph.locator(".node.traced.bad").filter({ hasText: "R-1.1" })).toBeVisible();
  await expect(graph.locator(".node.traced.bad").filter({ hasText: "ПР-01" })).toBeVisible();
  await expect(graph.locator(".edge.trace.missing")).toHaveCount(1);
  await expect(graph.locator("aside")).toContainText("Нарушения: 2");

  await graph.getByRole("button", { name: "Сбросить трассировку" }).click();
  await expect(graph.locator(".node.goal")).toHaveCount(0);
  await expect(graph.locator(".node.traced")).toHaveCount(0);
});

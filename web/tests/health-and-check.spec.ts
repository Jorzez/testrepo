import { expect, orderCard, test, toast } from "./fixtures";

test("переход из диагностики к атрибуту и к приказу", async ({ app }) => {
  await app.getByRole("tab", { name: /Диагностика/ }).click();
  await expect(app.getByText("Граф не готов к проверкам")).toBeVisible();

  const noDescription = app.locator(".issue").filter({ hasText: "Атрибуты без описания" });
  await noDescription.getByRole("button", { name: "Показать" }).click();
  await expect(app.getByRole("tab", { name: "Атрибуты" })).toHaveAttribute("aria-selected", "true");
  await expect(app.locator("tr").filter({ hasText: "обучение" })).toHaveClass(/flash/);

  await app.getByRole("tab", { name: /Диагностика/ }).click();
  const noKeys = app.locator(".issue").filter({ hasText: "Узлы без идентификатора" });
  await noKeys.locator(".item").filter({ hasText: "Rule" }).getByRole("button", { name: "Показать" }).click();
  await expect(app.getByRole("tab", { name: "Приказы и пункты" })).toHaveAttribute("aria-selected", "true");
  await expect(app.locator(".rule").filter({ hasText: "Обучение само по себе" })).toHaveClass(/flash/);
});

test("автопочинка идентификаторов", async ({ app }) => {
  await expect(orderCard(app, "ПР-02").getByText("нет orderId")).toBeVisible();
  await app.getByRole("tab", { name: /Диагностика/ }).click();
  await app.getByRole("button", { name: "Проставить идентификаторы" }).click();
  await app.getByRole("dialog").getByRole("button", { name: "Проставить" }).click();
  await expect(toast(app, "Проставлено: приказов 1, пунктов 1, правил 1")).toBeVisible();
  await expect(app.locator(".issue").filter({ hasText: "Узлы без идентификатора" })).toHaveCount(0);
  await app.getByRole("tab", { name: "Приказы и пункты" }).click();
  await expect(orderCard(app, "ПР-02").getByText("нет orderId")).toHaveCount(0);
});

test("значок на вкладке показывает число ошибок", async ({ app }) => {
  await expect(app.getByRole("tab", { name: /Диагностика/ }).locator(".badge.count.err")).toHaveText("2");
});

test("проверка цели показывает нарушения и примеры", async ({ app }) => {
  await app.getByRole("tab", { name: "Проверка цели" }).click();
  await app.getByLabel("Формулировка цели").fill("Снизить долю просроченных заявок до 5% к 31.12.2025");
  await app.getByRole("button", { name: "Проверить" }).click();
  const result = app.locator("#checkResult");
  await expect(result.getByText("Найдены нарушения")).toBeVisible();
  await expect(result.locator(".chip", { hasText: "срок_исполнения" }).first()).toBeVisible();
  const violation = result.locator(".violation").filter({ hasText: "Требование не выполнено" });
  await expect(violation).toContainText("ПР-01 1.1");
  await expect(violation.locator(".example.good")).toContainText("«Альфа»");

  // Результат не теряется при переключении вкладок.
  await app.getByRole("tab", { name: "Атрибуты" }).click();
  await app.getByRole("tab", { name: "Проверка цели" }).click();
  await expect(result.getByText("Найдены нарушения")).toBeVisible();
});

test("пустая цель не отправляется", async ({ app }) => {
  await app.getByRole("tab", { name: "Проверка цели" }).click();
  await app.getByRole("button", { name: "Проверить" }).click();
  await expect(toast(app, "Введите формулировку цели")).toBeVisible();
});

test("недоступный API виден в шапке", async ({ page }) => {
  await page.route("**/mockapi/**", (route) => route.abort());
  await page.goto("/?api=/mockapi");
  await expect(page.locator("header").getByText("API недоступен")).toBeVisible();
  await expect(toast(page, "Не удалось получить данные")).toBeVisible();
});

import { clauseBlock, expect, menu, openClause, orderCard, test, toast } from "./fixtures";

/* Сценарии, на которых прежний интерфейс уже ломался или которые легко
   сломать при переписывании. */

test("раскрывает приказ, пункт и правило без бизнес-ключей", async ({ app }) => {
  const card = orderCard(app, "ПР-02");
  await expect(card.getByText("нет orderId")).toBeVisible();
  await openClause(app, "ПР-02", "3.1");
  const clause = clauseBlock(app, "3.1");
  await expect(clause.getByText("нет clauseId")).toBeVisible();
  await expect(clause.getByText("Обучение само по себе целью не является")).toBeVisible();
  await expect(clause.getByText("нет ruleId")).toBeVisible();
});

test("приказы и пункты сворачиваются независимо", async ({ app }) => {
  await openClause(app, "ПР-01", "1.1");
  await clauseBlock(app, "2.4").locator(".clause-head").click();
  await expect(app.getByText("Цель обязана содержать упоминание проекта")).toBeVisible();
  await expect(app.getByText("Цель обязана содержать конкретный срок исполнения")).toBeVisible();

  await clauseBlock(app, "1.1").locator(".clause-head").click();
  await expect(app.getByText("Цель обязана содержать упоминание проекта")).toBeHidden();
  await expect(app.getByText("Цель обязана содержать конкретный срок исполнения")).toBeVisible();

  await app.getByRole("button", { name: "Свернуть" }).click();
  await expect(clauseBlock(app, "2.4")).toBeHidden();
  await app.getByRole("button", { name: "Раскрыть все" }).click();
  await expect(app.getByText("Обучение само по себе целью не является")).toBeVisible();
});

test("поиск раскрывает совпавшие узлы", async ({ app }) => {
  await app.getByPlaceholder(/Поиск по номеру/).fill("мониторинга");
  await expect(app.getByText("Внедрить систему мониторинга в проекте «Бета» до 15.09.2025")).toBeVisible();
  await expect(orderCard(app, "ПР-02")).toBeHidden();
  await app.getByPlaceholder(/Поиск по номеру/).fill("такого точно нет");
  await expect(app.getByText("Ничего не найдено.")).toBeVisible();
});

test("полный цикл по примерам", async ({ app }) => {
  await openClause(app, "ПР-01", "1.1");
  const rule = app.locator(".rule").filter({ hasText: "Цель обязана содержать упоминание проекта" });

  await menu(rule, "Создать пример");
  await app.getByLabel("Формулировка", { exact: true }).fill("В рамках проекта «Гамма» до 01.12.2025");
  await app.getByRole("button", { name: "Добавить" }).click();
  await expect(toast(app, "Пример добавлен")).toBeVisible();
  const example = rule.locator(".example").filter({ hasText: "«Гамма»" });
  await expect(example).toBeVisible();

  await example.getByRole("button", { name: "изменить" }).click();
  await app.getByLabel("Формулировка", { exact: true }).fill("В рамках проекта «Дельта» до 01.12.2025");
  await app.getByRole("button", { name: "Сохранить" }).click();
  const edited = rule.locator(".example").filter({ hasText: "«Дельта»" });
  await expect(edited).toBeVisible();

  await edited.getByRole("button", { name: "в архив" }).click();
  await expect(edited).toBeHidden();
  await app.locator("#tab-catalog").getByLabel("Архив").check();
  await expect(edited.getByText("в архиве")).toBeVisible();
  await edited.getByRole("button", { name: "вернуть" }).click();
  await expect(edited.getByText("в архиве")).toBeHidden();

  await edited.getByRole("button", { name: "удалить" }).click();
  await app.getByRole("dialog").getByRole("button", { name: "Удалить" }).click();
  await expect(toast(app, "Пример удалён")).toBeVisible();
  await expect(edited).toBeHidden();
});

test("редактор произвольных свойств", async ({ app }) => {
  await menu(orderCard(app, "ПР-01"), "Свойства");
  await app.getByRole("button", { name: "+ Свойство" }).click();
  const row = app.locator(".prop-row").last();
  await row.getByLabel("Имя свойства").fill("priority");
  await row.getByLabel("Тип свойства").selectOption("number");
  await row.getByLabel("Значение свойства").fill("3");
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "Свойства сохранены")).toBeVisible();

  await menu(orderCard(app, "ПР-01"), "Свойства");
  const saved = app.locator('.prop-row[data-prop="priority"]');
  await expect(saved.getByLabel("Тип свойства")).toHaveValue("number");
  await expect(saved.getByLabel("Значение свойства")).toHaveValue("3");
  await saved.getByTitle("Удалить свойство").click();
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "Свойства сохранены")).toBeVisible();

  await menu(orderCard(app, "ПР-01"), "Свойства");
  await expect(app.locator('.prop-row[data-prop="priority"]')).toHaveCount(0);
  await expect(app.locator('.prop-row[data-prop="date"] select')).toHaveValue("date");
});

test("правка ключа проверяет уникальность", async ({ app }) => {
  await orderCard(app, "ПР-01").locator(".order-head").click();
  await menu(clauseBlock(app, "1.1"), "Изменить");
  const key = app.getByLabel("Идентификатор (clauseId)");
  await key.fill("PR-01/2.4");
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "уже занят")).toBeVisible();
  await key.fill("PR-01/1.1-new");
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "Пункт обновлён")).toBeVisible();
});

test("перенос пункта в другой приказ", async ({ app }) => {
  await orderCard(app, "ПР-02").locator(".order-head").click();
  await menu(clauseBlock(app, "3.1"), "Перенести");
  await app.getByLabel("Приказ").selectOption({ label: "ПР-01" });
  await app.getByRole("button", { name: "Сохранить" }).click();
  await expect(toast(app, "Пункт перенесён")).toBeVisible();
  await expect(orderCard(app, "ПР-01").getByText("3 п. · 3 прав.")).toBeVisible();
  await expect(orderCard(app, "ПР-02").getByText("0 п. · 0 прав.")).toBeVisible();
});

test("удаление активного пункта без предварительного архивирования", async ({ app }) => {
  await orderCard(app, "ПР-01").locator(".order-head").click();
  await menu(clauseBlock(app, "2.4"), "Удалить");
  const dialog = app.getByRole("dialog");
  await expect(dialog).toContainText("вместе с 1 правил(а), 1 пример(ов)");
  await dialog.getByRole("button", { name: "Удалить" }).click();
  await expect(toast(app, "Удалено")).toBeVisible();
  await expect(clauseBlock(app, "2.4")).toBeHidden();
  await expect(orderCard(app, "ПР-01").getByText("1 п. · 1 прав.")).toBeVisible();
});

test("ввод экранируется, а не исполняется как HTML", async ({ app }) => {
  await app.locator("#tab-catalog").getByRole("button", { name: "Создать" }).click();
  await app.getByLabel("Номер").fill("ПР-99");
  await app.getByLabel("Заголовок").fill("<b>жирный</b><img src=x onerror=\"window.__xss=1\">");
  await app.getByRole("button", { name: "Создать" }).last().click();
  const card = orderCard(app, "ПР-99");
  await expect(card.getByText("<b>жирный</b>", { exact: false })).toBeVisible();
  await expect(card.locator("b", { hasText: "жирный" })).toHaveCount(0);
  await expect(card.locator("img")).toHaveCount(0);
  expect(await app.evaluate(() => (window as { __xss?: number }).__xss)).toBeUndefined();
});

test("меню действий: одно на экране, шире кнопки, закрывается", async ({ app }) => {
  // Меню нижнего приказа открывается под кнопкой и не перекрывает верхний.
  await orderCard(app, "ПР-02").getByRole("button", { name: "Действия" }).click();
  const button = orderCard(app, "ПР-01").getByRole("button", { name: "Действия" });
  await button.click();
  const popup = app.getByRole("menu");
  await expect(popup).toHaveCount(1);
  await expect(popup.getByRole("menuitem")).toHaveText(["Изменить", "Создать пункт", "Свойства", "В архив", "Удалить"]);
  const [menuBox, buttonBox] = [await popup.boundingBox(), await button.boundingBox()];
  expect(menuBox!.width).toBeGreaterThan(buttonBox!.width);

  await app.keyboard.press("Escape");
  await expect(popup).toBeHidden();
  await button.click();
  await app.locator("header").click({ position: { x: 5, y: 5 } });
  await expect(popup).toBeHidden();
  // Клик по «⋯» не раскрывает и не сворачивает приказ.
  await expect(orderCard(app, "ПР-01").locator(".body")).toHaveCount(0);
});

test("архивирование используемого атрибута спрашивает подтверждение", async ({ app }) => {
  await app.getByRole("tab", { name: "Атрибуты" }).click();
  const row = app.locator("tr").filter({ hasText: "срок_исполнения" });
  await menu(row, "В архив");
  await expect(app.getByRole("dialog")).toContainText("R-2.4");
  await app.getByRole("button", { name: "Отмена" }).click();
  await expect(row).toBeVisible();
  await menu(row, "В архив");
  await app.getByRole("button", { name: "Всё равно в архив" }).click();
  await expect(row).toBeHidden();
});

test("двойника атрибута по написанию создать нельзя", async ({ app }) => {
  await app.getByRole("tab", { name: "Атрибуты" }).click();
  await app.locator("#tab-targets").getByRole("button", { name: "Создать" }).click();
  await app.getByLabel("Имя").fill("Срок исполнения");
  await app.getByLabel("Описание для модели").fill("дата");
  await app.getByRole("button", { name: "Создать" }).last().click();
  await expect(toast(app, "уже есть")).toBeVisible();
  await expect(app.locator(".modal")).toBeVisible();
});

test("пустое обязательное поле не отправляется", async ({ app }) => {
  await app.locator("#tab-catalog").getByRole("button", { name: "Создать" }).click();
  await app.getByRole("button", { name: "Создать" }).last().click();
  await expect(toast(app, "Заполните поле «Номер»")).toBeVisible();
});

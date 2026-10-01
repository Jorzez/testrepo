import { expect, test as base, type Locator, type Page } from "@playwright/test";

import { createBackend } from "../mock/backend";

/* Каждый тест получает свой фейковый API. Запросы идут на тот же origin
   (/mockapi), поэтому CORS и preflight не мешают перехвату.

   В данных фейка: R-1.1 (проект) действует только в УЦТ и АГД; R-2.4 (срок)
   не применяется в АГД по «ПР-01 п. 2.5», а для финансового управления
   исключение — кандидат; приказ ПР-02 заведён без бизнес-ключей. */

export const test = base.extend<{ app: Page }>({
  app: async ({ page }, use) => {
    const backend = createBackend();
    await page.route("**/mockapi/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const raw = request.postData();
      const reply = backend.handle(request.method(), url.pathname.replace(/^\/mockapi/, "") + url.search,
        raw ? JSON.parse(raw) : undefined);
      await route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) });
    });
    await page.goto("/?api=/mockapi");
    await expect(page.getByText("API на связи")).toBeVisible();
    await use(page);
  },
});

export { expect };

export const PROJECT = "упоминание проекта";
export const DEADLINE = "конкретный срок исполнения";
export const TRAINING = "Обучение само по себе";

/** Перейти в раздел через боковую панель. */
export const go = (page: Page, section: string | RegExp) => page.getByRole("tab", { name: section }).click();

/** Диалоги, формы и окно ячейки живут в одном корне. */
export const modal = (page: Page) => page.locator("#modalRoot");

export const panel = (page: Page) => page.locator(".rule-panel");

export const orderItem = (page: Page, number: string) =>
  page.getByRole("option").filter({ has: page.locator(".n", { hasText: number }) });

/** Открытый в разделе «Приказы» документ приказа. */
export const orderDoc = (page: Page) => page.locator("#tab-orders .orders > [data-node]");

export const clauseBlock = (page: Page, code: string) =>
  page.locator(".clause").filter({ has: page.locator(".num", { hasText: new RegExp(`^${code.replace(".", "\\.")}$`) }) });

export const ruleCard = (page: Page, text: string) => page.locator(".rule-card").filter({ hasText: text });

export const matrixRow = (page: Page, rule: string) => page.locator("#tab-rules tbody tr").filter({ hasText: rule });

/** Ячейка матрицы «правило × подразделение». */
export const cell = (page: Page, rule: string, department: string) =>
  page.locator("#tab-rules").getByRole("button", { name: new RegExp(`${rule}.* — ${department}:`) });

/** Открыть меню «⋯» у объекта и выбрать пункт. */
export async function menu(owner: Locator, item: string) {
  await owner.getByRole("button", { name: "Действия" }).first().click();
  await owner.page().getByRole("menuitem", { name: item, exact: true }).click();
}

/** Последнее уведомление с таким текстом: одинаковые могут висеть одновременно. */
export const toast = (page: Page, text: string | RegExp) =>
  page.locator("#toasts .toast").filter({ hasText: text }).last();

/** Открыть панель правила из матрицы. */
export async function openRule(page: Page, rule: string) {
  await go(page, "Правила");
  await matrixRow(page, rule).locator("td.rule-col").click();
  await expect(panel(page)).toBeVisible();
}

/** Проверить цель на главном экране; возвращает карточку результата. */
export async function check(page: Page, goal: string, department: string | null = null) {
  await go(page, "Проверка цели");
  await page.getByLabel("Формулировка цели").fill(goal);
  await page.locator("#departmentInput").selectOption(department ?? "");
  await page.locator("#tab-check").getByRole("button", { name: "Проверить" }).click();
  return page.locator("#checkResult");
}

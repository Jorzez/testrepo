import { expect, test as base, type Locator, type Page } from "@playwright/test";

import { createBackend } from "../mock/backend";

/* Каждый тест получает свой фейковый API. Запросы идут на тот же origin
   (/mockapi), поэтому CORS и preflight не мешают перехвату. */

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

export const orderCard = (page: Page, number: string) =>
  page.locator(".card").filter({ has: page.locator(".order-title b", { hasText: number }) });

export const clauseBlock = (page: Page, code: string) =>
  page.locator(".clause").filter({ has: page.locator(".clause-head b", { hasText: code }) });

/** Открыть меню «⋯» у объекта и выбрать пункт. */
export async function menu(owner: Locator, item: string) {
  await owner.getByRole("button", { name: "Действия" }).first().click();
  await owner.page().getByRole("menuitem", { name: item, exact: true }).click();
}

/** Последнее уведомление с таким текстом: одинаковые могут висеть одновременно. */
export const toast = (page: Page, text: string | RegExp) =>
  page.locator("#toasts .toast").filter({ hasText: text }).last();

export async function openClause(page: Page, order: string, code: string) {
  await orderCard(page, order).locator(".order-head").click();
  await clauseBlock(page, code).locator(".clause-head").click();
}

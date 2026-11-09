// Headless screenshot of the running portal (synthetic data, localhost only).
import { chromium } from "playwright";

const out = process.argv[2] ?? "demo.png";
const browser = await chromium.launch({ channel: process.env.HR_E2E_CHANNEL || undefined });
const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
await page.goto("http://localhost:8000/");
await page.getByLabel("Password").fill(process.env.HR_DEMO_PASSWORD ?? "demo-only");
await page.getByRole("button", { name: "Sign in" }).click();
for (const question of [
  "How many unused annual leave days can be carried over?",
  "What is my leave balance?",
  "Show leave balance for E1006",
]) {
  const before = await page.locator("article").count();
  await page.getByLabel("Message").fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  await page.locator("article").nth(before).waitFor();
}
await page.screenshot({ path: out });
await browser.close();
console.log(`Wrote ${out}`);

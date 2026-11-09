// Automated WCAG 2.1 A/AA checks (axe-core) on the running portal: every screen, in real states.
// Automated tools catch only part of WCAG; this does not replace manual or screen-reader testing.
import { writeFileSync } from "node:fs";
import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";

const base = process.env.HR_E2E_URL ?? "http://localhost:8000";
const out = process.argv[2] ?? "a11y-report.json";
const browser = await chromium.launch({ channel: process.env.HR_E2E_CHANNEL || undefined });
const context = await browser.newContext({ viewport: { width: 1100, height: 760 } });
const page = await context.newPage();
const results = [];

async function scan(name) {
  const { violations, passes } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  results.push({
    screen: name,
    rules_passed: passes.length,
    violations: violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.html.slice(0, 160)) })),
  });
}

async function signIn(id) {
  await page.goto(base);
  await page.getByLabel("Demo user").selectOption(id);
  await page.getByLabel("Password").fill(process.env.HR_DEMO_PASSWORD ?? "demo-only");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: "Ask HR" }).waitFor();
}

async function ask(message) {
  const before = await page.locator("article").count();
  await page.getByLabel("Message").fill(message);
  await page.getByRole("button", { name: "Send" }).click();
  await page.locator("article").nth(before).waitFor();
}

async function open(tab, heading) {
  await page.getByRole("button", { name: tab, exact: true }).click();
  await page.getByRole("heading", { name: heading }).waitFor();
  await page.waitForLoadState("networkidle");
}

await page.goto(base);
await page.getByRole("button", { name: "Sign in" }).waitFor();
await scan("login");
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByRole("alert").waitFor();
await scan("login-error");

await signIn("E1005");
await ask("How many unused annual leave days can be carried over?");
await ask("Show leave balance for E1006");
await ask("My manager is harassing me");
await scan("assistant-with-denied-and-escalated-replies");
await open("My leave", "My leave");
await scan("my-leave");
await page.getByRole("button", { name: "Sign out" }).click();

await signIn("E1002");
await open("Approvals", "Awaiting your approval");
await scan("approvals");
await open("Escalations", "Escalations");
await scan("escalations");
await open("Audit log", "Audit log");
await scan("audit-log");

// Keyboard: focus must move to a control and show an outline.
await page.keyboard.press("Shift+Tab");
const keyboard = await page.evaluate(() => ({
  focus_moved_to: document.activeElement.tagName,
  outline: getComputedStyle(document.activeElement).outlineStyle,
}));
if (keyboard.focus_moved_to === "BODY" || keyboard.outline === "none") throw new Error(`Keyboard focus check failed: ${JSON.stringify(keyboard)}`);

// Negative control: a scan that cannot fail proves nothing, so plant known violations.
await page.evaluate(() => {
  document.body.insertAdjacentHTML("beforeend", '<img src="x.png"><p style="color:#eee;background:#fff">low contrast</p>');
});
const planted = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
const controlIds = planted.violations.map((v) => v.id);
if (!controlIds.includes("image-alt") || !controlIds.includes("color-contrast")) throw new Error(`Negative control failed: ${controlIds}`);

await browser.close();
const total = results.reduce((sum, r) => sum + r.violations.length, 0);
writeFileSync(out, `${JSON.stringify({ standard: "WCAG 2.1 A and AA (axe-core automated subset)", screens: results.length, violations: total, keyboard, negative_control_detected: controlIds, results }, null, 2)}\n`);
for (const r of results) console.log(r.screen, "passed", r.rules_passed, "violations", r.violations.map((v) => `${v.id}(${v.nodes.length})`).join(", ") || "none");
if (total) {
  console.error(`${total} accessibility rule violation(s).`);
  process.exit(1);
}

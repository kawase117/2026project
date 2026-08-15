async (page) => {
  const key = "codex_site777_full_collect_v4";
  if (!page.url().includes("www.d-deltanet.com")) {
    await page.goto(
      "https://www.d-deltanet.com/pc/D0301.do?pmc=22021006&clc=03&urt=2173&pan=1",
      { waitUntil: "domcontentloaded", timeout: 30000 },
    );
  }
  const value = await page.evaluate((storageKey) => localStorage.getItem(storageKey), key);
  return value ? JSON.parse(value) : null;
}

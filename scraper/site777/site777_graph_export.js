async (page) => {
  const storageKey = "codex_site777_graph_collect_v2";
  if (!page.url().includes("www.d-deltanet.com")) {
    await page.goto(
      "https://www.d-deltanet.com/pc/D0301.do?pmc=22021006&clc=03&urt=2173&pan=1",
      { waitUntil: "domcontentloaded" },
    );
  }
  const value = await page.evaluate((key) => localStorage.getItem(key), storageKey);
  return value ? JSON.parse(value) : null;
}

async (page) => {
  const config = __SITE777_UPDATE_GATE_CONFIG__;
  const listUrl =
    "https://www.d-deltanet.com/pc/D0301.do?pmc=22021006&clc=03&urt=2173&pan=1";
  const recoveryEvents = [];
  const context = page.context();
  let modelPage = null;
  let jackpotPage = null;

  const inspect = async (targetPage) => {
    const bodyText = await targetPage.locator("body").innerText();
    return {
      bodyText,
      errorCode: bodyText.match(/PNW\d+/)?.[0] ?? null,
      url: targetPage.url(),
    };
  };
  const inspectWithOneReload = async (targetPage, stage) => {
    let state = await inspect(targetPage);
    if (!state.errorCode) return state;
    await targetPage.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    state = await inspect(targetPage);
    recoveryEvents.push({ stage, errorCode: state.errorCode });
    return state;
  };
  const openByClick = async (parentPage, locator, stage) => {
    await parentPage.waitForTimeout(3000);
    const [targetPage] = await Promise.all([
      context.waitForEvent("page", { timeout: 30000 }),
      locator.click({ modifiers: ["Control"], timeout: 30000 }),
    ]);
    await targetPage.waitForLoadState("domcontentloaded", { timeout: 30000 });
    return { targetPage, state: await inspectWithOneReload(targetPage, stage) };
  };

  try {
    await page.goto(listUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    let state = await inspectWithOneReload(page, "machine_list:1");
    if (state.errorCode) return { ok: false, stage: "machine_list:1", ...state, recoveryEvents };
    let currentPage = 1;
    while (currentPage < config.listPage) {
      const next = page.getByRole("link", { name: "次へ", exact: true });
      if ((await next.count()) !== 1) throw new Error(`next link missing on list page ${currentPage}`);
      await page.waitForTimeout(3000);
      await Promise.all([
        page.waitForURL((url) => url.searchParams.get("pan") === String(currentPage + 1), { timeout: 30000 }),
        next.click({ timeout: 30000 }),
      ]);
      currentPage += 1;
      state = await inspectWithOneReload(page, `machine_list:${currentPage}`);
      if (state.errorCode) return { ok: false, stage: `machine_list:${currentPage}`, ...state, recoveryEvents };
    }

    const modelLocator = page.locator(`a[href*="D2301.do"][href*="mdc=${config.mdc}"]`);
    if ((await modelLocator.count()) !== 1) throw new Error("update-gate model link was not unique");
    const modelOpen = await openByClick(page, modelLocator, "model_menu");
    modelPage = modelOpen.targetPage;
    if (modelOpen.state.errorCode) return { ok: false, stage: "model_menu", ...modelOpen.state, recoveryEvents };

    const jackpotLink = modelPage.getByRole("link", { name: "大当り一覧", exact: true });
    if ((await jackpotLink.count()) !== 1) throw new Error("jackpot link was not unique");
    const jackpotOpen = await openByClick(modelPage, jackpotLink, "jackpot");
    jackpotPage = jackpotOpen.targetPage;
    if (jackpotOpen.state.errorCode) return { ok: false, stage: "jackpot", ...jackpotOpen.state, recoveryEvents };
    const currentUpdateTime = jackpotOpen.state.bodyText.match(
      /データ更新時間\s*(\d{4}\/\d{2}\/\d{2}\s+\d{2}:\d{2})/,
    )?.[1] ?? null;
    return {
      ok: Boolean(currentUpdateTime),
      checkedAt: new Date().toISOString(),
      model: config.modelName,
      mdc: config.mdc,
      previousUpdateTime: config.previousUpdateTime,
      currentUpdateTime,
      updated: !config.previousUpdateTime || currentUpdateTime > config.previousUpdateTime,
      recoveryEvents,
    };
  } catch (error) {
    return { ok: false, error: String(error?.message || error), recoveryEvents };
  } finally {
    for (const targetPage of [jackpotPage, modelPage]) {
      if (targetPage) try { await targetPage.close(); } catch {}
    }
  }
}

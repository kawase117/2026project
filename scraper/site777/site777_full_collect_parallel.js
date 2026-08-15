async (page) => {
  const priorSource = __SITE777_PRIOR_SOURCE__;
  const listUrl =
    "https://www.d-deltanet.com/pc/D0301.do?pmc=22021006&clc=03&urt=2173&pan=1";
  const storageKey = "codex_site777_full_collect_v4";
  const workerCount = 2;
  const sharedIntervalMs = 3000;
  const pipelineBatchLimit = __SITE777_FULL_BATCH_LIMIT__;
  const rateLimiterUrl = __SITE777_RATE_LIMITER_URL__;
  const recoveryDelaysMs = [0, 60000, 300000];
  const context = page.context();
  const trackedPages = new Set();
  let throttleChain = Promise.resolve();
  let persistChain = Promise.resolve();
  let lastRequestStartedAt = 0;
  let globalPauseUntil = 0;
  let aborted = false;
  let modelsClaimedThisRun = 0;
  let batchLimitReached = false;

  const blankState = () => ({
    version: 5,
    priorSnapshotId: priorSource?.completedAt ?? null,
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    complete: false,
    workerCount,
    sharedIntervalMs,
    recoveryDelaysMs,
    requestSeq: 0,
    expectedModelCount: null,
    expectedMachineCount: null,
    discoveredModels: [],
    models: {},
    accessLog: [],
    restrictionEvents: [],
    failures: [],
  });
  let state = blankState();

  const persist = async () => {
    state.updatedAt = new Date().toISOString();
    const value = JSON.stringify(state);
    persistChain = persistChain.then(() =>
      page.evaluate(
        ({ key, value: serialized }) => localStorage.setItem(key, serialized),
        { key: storageKey, value },
      ),
    );
    await persistChain;
  };

  const throttle = async () => {
    if (rateLimiterUrl) {
      const response = await page.request.get(
        `${rateLimiterUrl}/acquire?stream=normal`,
      );
      if (!response.ok()) {
        throw new Error(`shared rate limiter failed: ${response.status()}`);
      }
      const payload = await response.json();
      return Number(payload.waitMs ?? 0);
    }
    let release;
    const previous = throttleChain;
    throttleChain = new Promise((resolve) => {
      release = resolve;
    });
    await previous;
    const pauseMs = Math.max(0, globalPauseUntil - Date.now());
    if (pauseMs > 0) await page.waitForTimeout(pauseMs);
    const waitMs = Math.max(
      0,
      lastRequestStartedAt + sharedIntervalMs - Date.now(),
    );
    if (waitMs > 0) await page.waitForTimeout(waitMs);
    lastRequestStartedAt = Date.now();
    release();
    return waitMs;
  };

  const pauseAllStreams = async (delayMs) => {
    if (!rateLimiterUrl || delayMs <= 0) return;
    const response = await page.request.get(
      `${rateLimiterUrl}/pause?ms=${delayMs}`,
    );
    if (!response.ok()) {
      throw new Error(`shared rate limiter pause failed: ${response.status()}`);
    }
  };

  const inspect = async (targetPage) => {
    const bodyText = await targetPage.locator("body").innerText();
    return {
      bodyText,
      url: targetPage.url(),
      title: await targetPage.title(),
      errorCode: bodyText.match(/PNW\d+/)?.[0] ?? null,
    };
  };

  const recordAccess = async (stage, worker, waitMs, targetState) => {
    state.requestSeq += 1;
    state.accessLog.push({
      requestSeq: state.requestSeq,
      accessedAt: new Date().toISOString(),
      stage,
      worker,
      sharedWaitMs: waitMs,
      url: targetState.url,
      title: targetState.title,
      errorCode: targetState.errorCode,
      ok: !targetState.errorCode,
    });
    await persist();
  };

  const recover = async (targetPage, stage, worker, currentState) => {
    if (!currentState.errorCode) return currentState;
    const event = {
      detectedRequestSeq: state.requestSeq,
      detectedAt: new Date().toISOString(),
      stage,
      worker,
      errorCode: currentState.errorCode,
      attempts: [],
      recovered: false,
      recoveredAfterMs: null,
    };
    state.restrictionEvents.push(event);
    await persist();

    for (const delayMs of recoveryDelaysMs) {
      if (delayMs > 0) {
        globalPauseUntil = Math.max(globalPauseUntil, Date.now() + delayMs);
        await pauseAllStreams(delayMs);
      }
      const waitMs = await throttle();
      await targetPage.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
      currentState = await inspect(targetPage);
      await recordAccess(
        `${stage}:recovery_reload`,
        worker,
        waitMs + delayMs,
        currentState,
      );
      event.attempts.push({
        requestSeq: state.requestSeq,
        delayMs,
        errorCode: currentState.errorCode,
      });
      if (!currentState.errorCode) {
        event.recovered = true;
        event.recoveredAfterMs = delayMs;
        await persist();
        return currentState;
      }
    }
    await persist();
    return currentState;
  };

  const navigate = async (targetPage, stage, worker, action) => {
    if (aborted) throw new Error("collection aborted by another worker");
    const waitMs = await throttle();
    await action();
    let targetState = await inspect(targetPage);
    await recordAccess(stage, worker, waitMs, targetState);
    targetState = await recover(targetPage, stage, worker, targetState);
    return targetState;
  };

  const openInNewTab = async (parentPage, locator, stage, worker) => {
    if (aborted) throw new Error("collection aborted by another worker");
    const waitMs = await throttle();
    const [targetPage] = await Promise.all([
      context.waitForEvent("page", { timeout: 30000 }),
      locator.click({ modifiers: ["Control"], timeout: 30000 }),
    ]);
    trackedPages.add(targetPage);
    await targetPage.waitForLoadState("domcontentloaded", { timeout: 30000 });
    let targetState = await inspect(targetPage);
    await recordAccess(stage, worker, waitMs, targetState);
    targetState = await recover(targetPage, stage, worker, targetState);
    return { targetPage, targetState };
  };

  const closeTracked = async (targetPage) => {
    if (!targetPage) return;
    try {
      await targetPage.close();
    } catch {}
    trackedPages.delete(targetPage);
  };

  const extractDataPages = async (dataPage, stagePrefix, worker) => {
    const pages = [];
    let pageNumber = 1;
    let updateTime = null;
    while (pageNumber <= 20) {
      const bodyText = await dataPage.locator("body").innerText();
      updateTime ??=
        bodyText.match(
          /データ更新時間\s*(\d{4}\/\d{2}\/\d{2}\s+\d{2}:\d{2})/,
        )?.[1] ?? null;
      const rows = await dataPage.locator("table tr").evaluateAll((tableRows) =>
        tableRows.map((row) =>
          Array.from(row.querySelectorAll("th,td"), (cell) =>
            (cell.textContent || "").trim(),
          ),
        ),
      );
      pages.push({ pageNumber, url: dataPage.url(), rows });
      const next = dataPage.getByRole("link", { name: "次へ", exact: true });
      const nextCount = await next.count();
      if (nextCount === 0) break;
      if (nextCount !== 1) {
        throw new Error(`${stagePrefix}: ambiguous next link on page ${pageNumber}`);
      }
      const nextPageNumber = pageNumber + 1;
      const targetState = await navigate(
        dataPage,
        `${stagePrefix}:page_${nextPageNumber}`,
        worker,
        () =>
          Promise.all([
            dataPage.waitForURL(
              (url) => url.searchParams.get("pan") === String(nextPageNumber),
              { timeout: 30000 },
            ),
            next.click({ timeout: 30000 }),
          ]),
      );
      if (targetState.errorCode) {
        throw new Error(`${stagePrefix}: unrecovered ${targetState.errorCode}`);
      }
      pageNumber = nextPageNumber;
    }
    return { updateTime, pages };
  };

  const updateDate = (value) =>
    String(value || "").match(/\d{4}\/\d{2}\/\d{2}/)?.[0] ?? null;

  const numericGames = (dataset) => {
    const result = new Map();
    for (const pageItem of dataset?.pages ?? []) {
      for (const row of pageItem.rows ?? []) {
        const machineNumber = String(row?.[0] ?? "").trim();
        if (!/^\d+$/.test(machineNumber)) continue;
        const games = Number(String(row?.[1] ?? "").replace(/,/g, ""));
        if (!Number.isFinite(games)) return null;
        result.set(machineNumber, games);
      }
    }
    return result;
  };

  const numericRowCount = (dataset) => {
    const numbers = new Set();
    for (const pageItem of dataset?.pages ?? []) {
      for (const row of pageItem.rows ?? []) {
        const machineNumber = String(row?.[0] ?? "").trim();
        if (/^\d+$/.test(machineNumber)) numbers.add(machineNumber);
      }
    }
    return numbers.size;
  };

  const reusableHighest = (model, jackpot) => {
    const priorModel = priorSource?.models?.[model.mdc];
    if (
      !priorModel?.complete ||
      !priorModel.highest?.pages?.length ||
      numericRowCount(priorModel.highest) !== model.machineCount
    ) return null;
    if (
      !updateDate(jackpot.updateTime) ||
      updateDate(jackpot.updateTime) !== updateDate(priorModel.jackpot?.updateTime)
    ) return null;
    const currentGames = numericGames(jackpot);
    const priorGames = numericGames(priorModel.jackpot);
    if (
      !currentGames ||
      !priorGames ||
      currentGames.size !== model.machineCount ||
      priorGames.size !== currentGames.size
    ) return null;
    for (const [machineNumber, games] of currentGames) {
      if (priorGames.get(machineNumber) !== games) return null;
    }
    return {
      ...priorModel.highest,
      reused: true,
      reuseReason: "all_games_unchanged",
      reusedFromSnapshotId: priorSource.completedAt ?? null,
    };
  };

  const modelsOnPage = async (listPage, listPageNumber) =>
    listPage.locator('a[href*="D2301.do"]').evaluateAll(
      (links, pageNumber) =>
        links.map((link) => {
          const text = (link.textContent || "").trim();
          const href = link.getAttribute("href") || "";
          return {
            label: text,
            name: text.replace(/\s*\[\d+\]\s*$/, ""),
            machineCount: Number(text.match(/\[(\d+)\]\s*$/)?.[1] ?? 1),
            mdc: href.match(/[?&]mdc=(\d+)/)?.[1] ?? null,
            href,
            listPage: pageNumber,
          };
        }),
      listPageNumber,
    );

  const discoverModels = async () => {
    const discoveryPage = page;
    const firstState = await navigate(
      discoveryPage,
      "discovery:machine_list:1",
      "discovery",
      () => discoveryPage.goto(listUrl, { waitUntil: "domcontentloaded", timeout: 30000 }),
    );
    if (firstState.errorCode) throw new Error(`discovery ${firstState.errorCode}`);
    const discovered = [];
    let listPageNumber = 1;
    while (listPageNumber <= 20) {
      discovered.push(...(await modelsOnPage(discoveryPage, listPageNumber)));
      const next = discoveryPage.getByRole("link", { name: "次へ", exact: true });
      if ((await next.count()) === 0) break;
      const nextPageNumber = listPageNumber + 1;
      const nextState = await navigate(
        discoveryPage,
        `discovery:machine_list:${nextPageNumber}`,
        "discovery",
        () =>
          Promise.all([
            discoveryPage.waitForURL(
              (url) => url.searchParams.get("pan") === String(nextPageNumber),
              { timeout: 30000 },
            ),
            next.click({ timeout: 30000 }),
          ]),
      );
      if (nextState.errorCode) throw new Error(`discovery ${nextState.errorCode}`);
      listPageNumber = nextPageNumber;
    }
    return discovered.filter((model) => model.mdc);
  };

  const moveListPage = async (workerPage, currentPage, targetPage, worker) => {
    let pageNumber = currentPage;
    while (pageNumber < targetPage) {
      const next = workerPage.getByRole("link", { name: "次へ", exact: true });
      if ((await next.count()) !== 1) {
        throw new Error(`worker ${worker}: next list link missing on ${pageNumber}`);
      }
      const nextPageNumber = pageNumber + 1;
      const nextState = await navigate(
        workerPage,
        `worker:${worker}:machine_list:${nextPageNumber}`,
        worker,
        () =>
          Promise.all([
            workerPage.waitForURL(
              (url) => url.searchParams.get("pan") === String(nextPageNumber),
              { timeout: 30000 },
            ),
            next.click({ timeout: 30000 }),
          ]),
      );
      if (nextState.errorCode) throw new Error(`unrecovered ${nextState.errorCode}`);
      pageNumber = nextPageNumber;
    }
    return pageNumber;
  };

  const collectModel = async (workerPage, model, worker) => {
    let modelPage;
    let jackpotPage;
    let highestPage;
    try {
      const locator = workerPage.locator(`a[href="${model.href}"]`);
      if ((await locator.count()) !== 1) {
        throw new Error("unique model link was not found");
      }
      const modelOpen = await openInNewTab(
        workerPage,
        locator,
        `model:${model.mdc}:menu`,
        worker,
      );
      modelPage = modelOpen.targetPage;
      if (modelOpen.targetState.errorCode) {
        throw new Error(`unrecovered ${modelOpen.targetState.errorCode}`);
      }

      const jackpotLink = modelPage.getByRole("link", {
        name: "大当り一覧",
        exact: true,
      });
      const jackpotOpen = await openInNewTab(
        modelPage,
        jackpotLink,
        `model:${model.mdc}:jackpot:page_1`,
        worker,
      );
      jackpotPage = jackpotOpen.targetPage;
      if (jackpotOpen.targetState.errorCode) {
        throw new Error(`unrecovered ${jackpotOpen.targetState.errorCode}`);
      }
      const jackpot = await extractDataPages(
        jackpotPage,
        `model:${model.mdc}:jackpot`,
        worker,
      );
      await closeTracked(jackpotPage);
      jackpotPage = null;

      let highest = reusableHighest(model, jackpot);
      if (!highest) {
        const highestLink = modelPage.getByRole("link", {
          name: "最高出玉",
          exact: true,
        });
        const highestOpen = await openInNewTab(
          modelPage,
          highestLink,
          `model:${model.mdc}:highest:page_1`,
          worker,
        );
        highestPage = highestOpen.targetPage;
        if (highestOpen.targetState.errorCode) {
          throw new Error(`unrecovered ${highestOpen.targetState.errorCode}`);
        }
        highest = await extractDataPages(
          highestPage,
          `model:${model.mdc}:highest`,
          worker,
        );
        highest.reused = false;
        await closeTracked(highestPage);
        highestPage = null;
      }
      await closeTracked(modelPage);
      modelPage = null;

      state.models[model.mdc] = {
        ...model,
        complete: true,
        worker,
        completedAt: new Date().toISOString(),
        jackpot,
        highest,
      };
      await persist();
    } finally {
      await closeTracked(highestPage);
      await closeTracked(jackpotPage);
      await closeTracked(modelPage);
    }
  };

  const summary = (ok, stoppedAt = null, reason = null) => {
    const completed = Object.values(state.models).filter((model) => model.complete);
    return {
      ok,
      complete: state.complete,
      stoppedAt,
      reason,
      workerCount,
      sharedIntervalMs,
      requestSeq: state.requestSeq,
      expectedModels: state.expectedModelCount,
      completedModels: completed.length,
      expectedMachines: state.expectedMachineCount,
      completedMachines: completed.reduce(
        (sum, model) => sum + model.machineCount,
        0,
      ),
      highestCollectedModels: completed.filter((model) => !model.highest?.reused).length,
      highestReusedModels: completed.filter((model) => model.highest?.reused).length,
      restrictions: state.restrictionEvents.length,
      failures: state.failures.length,
      startedAt: state.startedAt,
      updatedAt: state.updatedAt,
    };
  };

  try {
    await throttle();
    await page.goto(listUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    const savedText = await page.evaluate((key) => localStorage.getItem(key), storageKey);
    if (savedText) {
      const saved = JSON.parse(savedText);
      if (
        saved?.version === 5 &&
        saved?.priorSnapshotId === (priorSource?.completedAt ?? null)
      ) state = saved;
    }

    const models = await discoverModels();
    state.discoveredModels = models;
    state.expectedModelCount = models.length;
    state.expectedMachineCount = models.reduce(
      (sum, model) => sum + model.machineCount,
      0,
    );
    await persist();

    const workerPages = [];
    for (let worker = 0; worker < workerCount; worker += 1) {
      const workerPage = await context.newPage();
      trackedPages.add(workerPage);
      const firstState = await navigate(
        workerPage,
        `worker:${worker}:machine_list:1`,
        worker,
        () => workerPage.goto(listUrl, { waitUntil: "domcontentloaded", timeout: 30000 }),
      );
      if (firstState.errorCode) throw new Error(`worker ${worker} ${firstState.errorCode}`);
      workerPages.push(workerPage);
    }

    const assignments = Array.from({ length: workerCount }, () => []);
    models.forEach((model, index) => assignments[index % workerCount].push(model));
    const runWorker = async (worker) => {
      const workerPage = workerPages[worker];
      let currentListPage = 1;
      for (const model of assignments[worker]) {
        if (aborted) break;
        if (state.models[model.mdc]?.complete) continue;
        if (
          pipelineBatchLimit > 0 &&
          modelsClaimedThisRun >= pipelineBatchLimit
        ) {
          batchLimitReached = true;
          break;
        }
        modelsClaimedThisRun += 1;
        currentListPage = await moveListPage(
          workerPage,
          currentListPage,
          model.listPage,
          worker,
        );
        try {
          await collectModel(workerPage, model, worker);
        } catch (error) {
          aborted = true;
          state.failures.push({
            at: new Date().toISOString(),
            worker,
            listPage: model.listPage,
            mdc: model.mdc,
            model: model.name,
            message: String(error?.message || error),
            requestSeq: state.requestSeq,
          });
          await persist();
          throw error;
        }
      }
    };

    await Promise.all(Array.from({ length: workerCount }, (_, worker) => runWorker(worker)));
    for (const workerPage of workerPages) await closeTracked(workerPage);

    const completed = Object.values(state.models).filter((model) => model.complete);
    state.complete =
      completed.length === state.expectedModelCount &&
      completed.reduce((sum, model) => sum + model.machineCount, 0) ===
        state.expectedMachineCount;
    state.completedAt = new Date().toISOString();
    await persist();
    return summary(
      true,
      state.complete
        ? null
        : batchLimitReached
          ? "batch_limit"
          : "completion_check",
    );
  } catch (error) {
    aborted = true;
    for (const targetPage of [...trackedPages]) await closeTracked(targetPage);
    if (!state.failures.some((failure) => failure.requestSeq === state.requestSeq)) {
      state.failures.push({
        at: new Date().toISOString(),
        message: String(error?.message || error),
        requestSeq: state.requestSeq,
      });
    }
    try {
      await persist();
    } catch {}
    return summary(false, "collector", String(error?.message || error));
  }
}

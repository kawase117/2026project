async (page) => {
  const targetConfig = __SITE777_TARGET_CONFIG__;
  const collectTargets = targetConfig.targets.filter(
    (target) => target.action !== "reuse",
  );
  const targetKeys = new Set(collectTargets.map((target) => target.key));
  const targetModels = new Set(collectTargets.map((target) => target.mdc));
  const listUrl =
    "https://www.d-deltanet.com/pc/D0301.do?pmc=22021006&clc=03&urt=2173&pan=1";
  const storageKey = "codex_site777_graph_collect_v2";
  const baseDelayMs = targetConfig.sharedIntervalMs ?? 2500;
  const rateLimiterUrl = targetConfig.rateLimiterUrl ?? "";
  const recoveryDelaysMs = [0, 60000, 300000];
  const maxNewMachinesPerRun = 50;
  const imageDirectory = targetConfig.imageDirectory;
  const context = page.context();
  let openPages = [];

  const blankState = () => ({
    version: 3,
    sourceSnapshotId: targetConfig.sourceSnapshotId,
    sourceComplete: targetConfig.sourceComplete ?? true,
    sourceStartedAt: targetConfig.sourceStartedAt,
    sourceCompletedAt: targetConfig.sourceCompletedAt,
    graphMinGames: targetConfig.graphMinGames,
    allMachineCount: targetConfig.allMachineCount,
    targetCount: targetConfig.targetCount,
    collectTargetCount: targetConfig.collectTargetCount ?? collectTargets.length,
    reuseCount: targetConfig.reuseCount ?? 0,
    excludedCount: targetConfig.excludedCount,
    targetModelCount: targetConfig.targetModelCount,
    targets: targetConfig.targets,
    imageDirectory,
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    complete: false,
    baseDelayMs,
    recoveryDelaysMs,
    requestSeq: 0,
    models: {},
    machines: {},
    accessLog: [],
    restrictionEvents: [],
    failures: [],
  });
  let state = blankState();
  let newMachinesThisRun = 0;

  const syncTargetConfig = () => {
    state.sourceComplete = targetConfig.sourceComplete ?? true;
    state.sourceStartedAt = targetConfig.sourceStartedAt;
    state.sourceCompletedAt = targetConfig.sourceCompletedAt;
    state.allMachineCount = targetConfig.allMachineCount;
    state.targetCount = targetConfig.targetCount;
    state.collectTargetCount =
      targetConfig.collectTargetCount ?? collectTargets.length;
    state.reuseCount = targetConfig.reuseCount ?? 0;
    state.excludedCount = targetConfig.excludedCount;
    state.targetModelCount = targetConfig.targetModelCount;
    state.targets = targetConfig.targets;
    state.imageDirectory = imageDirectory;
    for (const mdc of targetModels) {
      if (state.models[mdc]?.skipped) delete state.models[mdc];
    }
    state.complete = false;
  };

  const persist = async () => {
    state.updatedAt = new Date().toISOString();
    await page.evaluate(
      ({ key, value }) => localStorage.setItem(key, value),
      { key: storageKey, value: JSON.stringify(state) },
    );
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

  const throttle = async () => {
    if (!rateLimiterUrl) {
      if (baseDelayMs > 0) await page.waitForTimeout(baseDelayMs);
      return baseDelayMs;
    }
    const response = await page.request.get(
      `${rateLimiterUrl}/acquire?stream=graph`,
    );
    if (!response.ok()) {
      throw new Error(`shared rate limiter failed: ${response.status()}`);
    }
    const payload = await response.json();
    return Number(payload.waitMs ?? 0);
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

  const recordAccess = async (stage, delayMs, targetState) => {
    state.requestSeq += 1;
    state.accessLog.push({
      requestSeq: state.requestSeq,
      accessedAt: new Date().toISOString(),
      stage,
      delayMs,
      url: targetState.url,
      title: targetState.title,
      errorCode: targetState.errorCode,
      ok: !targetState.errorCode,
    });
    await persist();
  };

  const recover = async (targetPage, stage, currentState) => {
    if (!currentState.errorCode) return currentState;
    const event = {
      detectedRequestSeq: state.requestSeq,
      detectedAt: new Date().toISOString(),
      stage,
      errorCode: currentState.errorCode,
      attempts: [],
      recovered: false,
      recoveredAfterMs: null,
    };
    state.restrictionEvents.push(event);
    await persist();

    for (const delayMs of recoveryDelaysMs) {
      if (delayMs > 0) {
        await pauseAllStreams(delayMs);
        if (!rateLimiterUrl) await targetPage.waitForTimeout(delayMs);
      }
      const waitMs = await throttle();
      await targetPage.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
      currentState = await inspect(targetPage);
      await recordAccess(`${stage}:recovery_reload`, waitMs, currentState);
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

  const navigate = async (targetPage, stage, action, delayMs = baseDelayMs) => {
    let waitedMs;
    if (rateLimiterUrl) {
      waitedMs = await throttle();
    } else {
      if (delayMs > 0) await targetPage.waitForTimeout(delayMs);
      waitedMs = delayMs;
    }
    await action();
    let targetState = await inspect(targetPage);
    await recordAccess(stage, waitedMs, targetState);
    targetState = await recover(targetPage, stage, targetState);
    return targetState;
  };

  const openLinkInNewTab = async (parentPage, locator, stage) => {
    const waitedMs = await throttle();
    const [targetPage] = await Promise.all([
      context.waitForEvent("page"),
      locator.evaluate((element) => {
        element.target = "_blank";
        element.click();
      }),
    ]);
    openPages.push(targetPage);
    await targetPage.waitForLoadState("domcontentloaded", { timeout: 30000 });
    let targetState = await inspect(targetPage);
    await recordAccess(stage, waitedMs, targetState);
    targetState = await recover(targetPage, stage, targetState);
    return { targetPage, targetState };
  };

  const closeTracked = async (targetPage) => {
    if (!targetPage) return;
    try {
      await targetPage.close();
    } catch {}
    openPages = openPages.filter((candidate) => candidate !== targetPage);
  };

  const parseCount = (label) => {
    const match = label.match(/\[(\d+)\]\s*$/);
    return match ? Number(match[1]) : 1;
  };

  const summary = (ok, stoppedAt = null, reason = null) => ({
    ok,
    complete: state.complete,
    stoppedAt,
    reason,
    requestSeq: state.requestSeq,
    completedModels: Object.values(state.models).filter((item) => item.complete)
      .length,
    completedMachines: Object.values(state.machines).filter(
      (item) => item.complete,
    ).length,
    targetCount: state.targetCount,
    collectTargetCount: state.collectTargetCount,
    reuseCount: state.reuseCount,
    excludedCount: state.excludedCount,
    graphMinGames: state.graphMinGames,
    restrictions: state.restrictionEvents.length,
    failures: state.failures.length,
    startedAt: state.startedAt,
    updatedAt: state.updatedAt,
  });

  try {
    const initialWaitMs = await throttle();
    await page.goto(listUrl, { waitUntil: "domcontentloaded" });
    let listState = await inspect(page);
    const savedText = await page.evaluate((key) => localStorage.getItem(key), storageKey);
    if (savedText) {
      const saved = JSON.parse(savedText);
      if (
        saved?.version === 3 &&
        saved?.sourceSnapshotId === targetConfig.sourceSnapshotId &&
        saved?.graphMinGames === targetConfig.graphMinGames
      ) state = saved;
    }
    syncTargetConfig();
    await persist();
    await recordAccess("machine_list:1", initialWaitMs, listState);
    listState = await recover(page, "machine_list:1", listState);
    if (listState.errorCode) {
      return summary(false, "machine_list:1", listState.errorCode);
    }
    if (targetKeys.size === 0) {
      state.complete = state.sourceComplete;
      state.completedAt = new Date().toISOString();
      await persist();
      return summary(
        true,
        state.complete ? null : "source_incomplete",
      );
    }

    let listPageNumber = 1;
    while (listPageNumber <= 20) {
      const pageModels = await page
        .locator('a[href*="D2301.do"]')
        .evaluateAll((links) =>
          links.map((link) => {
            const label = (link.textContent || "").trim();
            const href = link.getAttribute("href") || "";
            return {
              label,
              name: label.replace(/\s*\[\d+\]\s*$/, ""),
              href,
              mdc: href.match(/[?&]mdc=(\d+)/)?.[1] ?? null,
            };
          }),
        );

      for (const model of pageModels) {
        if (!model.mdc || state.models[model.mdc]?.complete) continue;
        if (!targetModels.has(model.mdc)) {
          state.models[model.mdc] = {
            complete: true,
            skipped: true,
            completedAt: new Date().toISOString(),
            name: model.name,
            expectedTargets: 0,
            listPage: listPageNumber,
          };
          continue;
        }

        let modelPage;
        let graphListPage;
        try {
          const modelLocator = page.locator(`a[href="${model.href}"]`);
          if ((await modelLocator.count()) !== 1) {
            throw new Error("unique model link was not found");
          }
          const modelOpen = await openLinkInNewTab(
            page,
            modelLocator,
            `model:${model.mdc}:menu`,
          );
          modelPage = modelOpen.targetPage;
          if (modelOpen.targetState.errorCode) {
            throw new Error(`unrecovered ${modelOpen.targetState.errorCode}`);
          }

          const graphLink = modelPage.getByRole("link", {
            name: "出玉推移グラフ",
            exact: true,
          });
          if ((await graphLink.count()) !== 1) {
            throw new Error("unique graph-list link was not found");
          }
          const graphOpen = await openLinkInNewTab(
            modelPage,
            graphLink,
            `model:${model.mdc}:graph_list:1`,
          );
          graphListPage = graphOpen.targetPage;
          if (graphOpen.targetState.errorCode) {
            throw new Error(`unrecovered ${graphOpen.targetState.errorCode}`);
          }

          let graphListNumber = 1;
          let discoveredMachines = 0;
          while (graphListNumber <= 20) {
            const machineLinks = await graphListPage
              .locator('a[href*="D3001.do"]')
              .evaluateAll((links) =>
                links.map((link) => ({
                  label: (link.textContent || "").trim(),
                  href: link.getAttribute("href") || "",
                })),
              );

            for (const machine of machineLinks) {
              const machineNumber =
                machine.href.match(/[?&]dn=(\d+)/)?.[1] ?? machine.label;
              if (!/^\d+$/.test(machineNumber)) continue;
              discoveredMachines += 1;
              const key = `${model.mdc}:${machineNumber}`;
              if (!targetKeys.has(key)) continue;
              if (state.machines[key]?.complete) continue;

              let machinePage;
              try {
                const locator = graphListPage.locator(`a[href="${machine.href}"]`);
                if ((await locator.count()) !== 1) {
                  throw new Error("unique machine graph link was not found");
                }
                const machineOpen = await openLinkInNewTab(
                  graphListPage,
                  locator,
                  `model:${model.mdc}:machine:${machineNumber}`,
                );
                machinePage = machineOpen.targetPage;
                if (machineOpen.targetState.errorCode) {
                  throw new Error(`unrecovered ${machineOpen.targetState.errorCode}`);
                }

                let graphImage = machinePage.locator("#graph_image");
                if ((await graphImage.count()) !== 1) {
                  throw new Error("graph image was not found");
                }
                let imageReady = false;
                for (let attempt = 1; attempt <= 5; attempt += 1) {
                  const preview = await graphImage.screenshot();
                  if (preview.length >= 2500) {
                    imageReady = true;
                    break;
                  }
                  await machinePage.waitForTimeout(3000);
                }
                if (!imageReady) {
                  const refreshed = await navigate(
                    machinePage,
                    `model:${model.mdc}:machine:${machineNumber}:blank_graph_reload`,
                    () => machinePage.reload({ waitUntil: "domcontentloaded", timeout: 30000 }),
                    0,
                  );
                  if (refreshed.errorCode) {
                    throw new Error(`unrecovered ${refreshed.errorCode}`);
                  }
                  graphImage = machinePage.locator("#graph_image");
                  for (let attempt = 1; attempt <= 5; attempt += 1) {
                    const preview = await graphImage.screenshot();
                    if (preview.length >= 2500) {
                      imageReady = true;
                      break;
                    }
                    await machinePage.waitForTimeout(3000);
                  }
                }
                if (!imageReady) {
                  throw new Error("graph image remained blank after one reload");
                }
                const imagePath = `${imageDirectory}/${model.mdc}_${machineNumber}.png`;
                await graphImage.screenshot({ path: imagePath });
                const bodyText = machineOpen.targetState.bodyText;
                const updateTime =
                  bodyText.match(
                    /データ更新時間\s*(\d{4}\/\d{2}\/\d{2}\s+\d{2}:\d{2})/,
                  )?.[1] ?? null;
                const lamp = await machinePage.evaluate(() => {
                  const value = (selector) =>
                    document.querySelector(selector)?.textContent?.trim() ?? null;
                  return {
                    bb: value(".bb"),
                    rb: value(".rb"),
                    art: value(".art"),
                    totalGames: value(".total"),
                    currentGames: value(".now"),
                    highestPayout: value(".range"),
                    combinedProbability: value(".probability"),
                  };
                });

                state.machines[key] = {
                  complete: true,
                  completedAt: new Date().toISOString(),
                  mdc: model.mdc,
                  modelName: model.name,
                  machineNumber,
                  updateTime,
                  graphPageUrl: machinePage.url(),
                  imagePath,
                  lamp,
                };
                newMachinesThisRun += 1;
                await persist();
                await closeTracked(machinePage);
                machinePage = null;
                if (newMachinesThisRun >= maxNewMachinesPerRun) {
                  await closeTracked(graphListPage);
                  graphListPage = null;
                  await closeTracked(modelPage);
                  modelPage = null;
                  return summary(
                    false,
                    "batch_limit",
                    `saved ${newMachinesThisRun} new machines in this batch`,
                  );
                }
              } catch (error) {
                await closeTracked(machinePage);
                throw error;
              }
            }

            const next = graphListPage.getByRole("link", {
              name: "次へ",
              exact: true,
            });
            const nextCount = await next.count();
            if (nextCount === 0) break;
            if (nextCount !== 1) {
              throw new Error("ambiguous graph-list next link");
            }
            const nextGraphList = graphListNumber + 1;
            const nextState = await navigate(
              graphListPage,
              `model:${model.mdc}:graph_list:${nextGraphList}`,
              () => {
                const expectedPage = String(nextGraphList);
                return Promise.all([
                  graphListPage.waitForURL(
                    (url) => url.searchParams.get("pan") === expectedPage,
                    { timeout: 30000 },
                  ),
                  next.click({ timeout: 30000 }),
                ]);
              },
            );
            if (nextState.errorCode) {
              throw new Error(`unrecovered ${nextState.errorCode}`);
            }
            graphListNumber = nextGraphList;
          }

          const expectedMachines = parseCount(model.label);
          state.models[model.mdc] = {
            complete: discoveredMachines === expectedMachines,
            completedAt: new Date().toISOString(),
            name: model.name,
            expectedMachines,
            discoveredMachines,
            graphListPages: graphListNumber,
            listPage: listPageNumber,
          };
          if (discoveredMachines !== expectedMachines) {
            throw new Error(
              `machine count mismatch: expected=${expectedMachines}, discovered=${discoveredMachines}`,
            );
          }
          await persist();
          await closeTracked(graphListPage);
          graphListPage = null;
          await closeTracked(modelPage);
          modelPage = null;
        } catch (error) {
          await closeTracked(graphListPage);
          await closeTracked(modelPage);
          state.failures.push({
            at: new Date().toISOString(),
            listPage: listPageNumber,
            mdc: model.mdc,
            model: model.name,
            message: String(error?.message || error),
            requestSeq: state.requestSeq,
          });
          await persist();
          return summary(false, `model:${model.mdc}`, String(error?.message || error));
        }
      }

      const next = page.getByRole("link", { name: "次へ", exact: true });
      const nextCount = await next.count();
      if (nextCount === 0) break;
      if (nextCount !== 1) {
        throw new Error(`ambiguous machine-list next link on page ${listPageNumber}`);
      }
      const nextList = listPageNumber + 1;
      listState = await navigate(
        page,
        `machine_list:${nextList}`,
        () => {
          const expectedPage = String(nextList);
          return Promise.all([
            page.waitForURL(
              (url) => url.searchParams.get("pan") === expectedPage,
              { timeout: 30000 },
            ),
            next.click({ timeout: 30000 }),
          ]);
        },
      );
      if (listState.errorCode) {
        return summary(false, `machine_list:${nextList}`, listState.errorCode);
      }
      listPageNumber = nextList;
    }

    state.complete =
      state.sourceComplete &&
      Object.values(state.machines).filter((item) => item.complete).length ===
        targetKeys.size &&
      [...targetKeys].every((key) => state.machines[key]?.complete);
    state.completedAt = new Date().toISOString();
    await persist();
    return summary(
      true,
      state.complete
        ? null
        : state.sourceComplete
          ? "completion_check"
          : "source_incomplete",
    );
  } catch (error) {
    for (const targetPage of [...openPages]) await closeTracked(targetPage);
    state.failures.push({
      at: new Date().toISOString(),
      message: String(error?.message || error),
      requestSeq: state.requestSeq,
    });
    try {
      await persist();
    } catch {}
    return summary(false, "collector", String(error?.message || error));
  }
}

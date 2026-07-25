/**
 * @typedef {"watching"|"detected"|"analyzing"|"customizing"|"generating"|"result"} AppStage
 * @typedef {"pending"|"active"|"done"|"error"} StepStatus
 */

const app = document.querySelector("#app");
const toast = document.querySelector("#toast");

const state = {
  /** @type {AppStage} */
  stage: "watching",
  data: null,
  videoError: false,
  isPlaying: false,
  userPauseIntent: false,
  showDrawer: false,
  selectedTags: new Set(),
  requirementText: "",
  formError: "",
  submitting: false,
  analysis: { progress: 0, steps: [] },
  generation: { progress: 0, message: "" },
  baseRecipe: null,
  personalizedRecipe: null,
  identifyResult: null,
  commentInsights: null,
  pauseFrame: "",
  activeTab: "recipe",
  stepOverlayIndex: null,
  timers: new Set(),
  controllers: new Set(),
};

const AS = "./public/assets";
const DEMO_PATH = "./public/demo-data/demoData.json";
const isDev = location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:";
const showDebugControls = new URLSearchParams(location.search).get("debug") === "1";

const analysisIcons = {
  identify: `${AS}/icons/status/subject.png`,
  retrieve: `${AS}/icons/status/course.png`,
  extract: `${AS}/icons/status/recipe.png`,
  comments: `${AS}/icons/status/feedback.png`,
  synthesize: `${AS}/icons/status/check_success.png`,
};

const fallbackPitfalls = [
  { problem: "出炉后塌陷", reason: "外壳没有彻底烤干或过早开盖。", solution: "前 15 分钟不要打开空气炸锅，后段低温补烤 3-5 分钟。" },
  { problem: "内部湿黏", reason: "面糊含水偏高或烘烤时间不足。", solution: "加蛋液分次少量加入，面糊到倒三角状态就停止。" },
  { problem: "空气炸锅上色过快", reason: "热风距离近，顶部先焦。", solution: "定型后盖一小片锡纸，温度下调 10 度。" },
  { problem: "面糊状态不正确", reason: "鸡蛋一次加入过多。", solution: "最后半个蛋液按勺加入，边搅拌边观察边缘下垂速度。" },
];

const stepDetails = [
  { action: "水、黄油、糖和盐入锅加热到沸腾。", keyState: "黄油完全融化，液体持续冒泡。", risk: "未沸腾会导致面粉糊化不足。" },
  { action: "关小火倒入低筋面粉，快速翻拌成团。", keyState: "锅底出现薄膜，面团不粘锅壁。", risk: "搅拌太慢会有干粉结块。" },
  { action: "面团降温后分次加入蛋液。", keyState: "刮刀提起呈倒三角。", risk: "蛋液过量会导致塌陷。" },
  { action: "确认面糊细腻、有光泽、能缓慢下垂。", keyState: "边缘平滑，不是流动液体。", risk: "太稀要停止加蛋液。" },
  { action: "用保鲜袋剪口挤入炸篮，保留间距。", keyState: "每个约 4cm，表面喷少量水。", risk: "距离太近会粘连。" },
  { action: "空气炸锅 170 度定型，后段 150 度烤干。", keyState: "外壳金黄且拿起变轻。", risk: "中途频繁打开会回缩。" },
  { action: "完全放凉后从底部开口填入奶油。", keyState: "外壳干爽，内部空心。", risk: "热的时候填馅会融化。" },
];

init();

async function init() {
  state.data = await loadDemoData();
  state.requirementText = state.data.defaultRequirement || "";
  state.baseRecipe = state.data.baseRecipe;
  state.personalizedRecipe = enrichRecipe(state.data.personalizedRecipe, state.data.baseRecipe);
  render();
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.stage === "detected") {
      continueWatching();
    } else if (event.key === "Escape" && state.stepOverlayIndex !== null) {
      state.stepOverlayIndex = null;
      render();
    }
  });
}

async function loadDemoData() {
  try {
    return normalizeAssetPaths(await request(DEMO_PATH, {}, 6000));
  } catch {
    return {
      currentVideo: {
        id: "local_001",
        title: "外酥里软！零失败泡芙教程",
        author: "@烘焙小厨",
        videoUrl: "",
        poster: `${AS}/food/pastry_hero_photo.png`,
        category: "泡芙",
        stats: { likes: "12.3w", comments: "3421", favorites: "9.8w", shares: "2.1w" },
      },
      analysisSteps: [],
      baseRecipe: {},
      requirementTags: ["减糖", "新手友好", "少食材", "空气炸锅", "无裱花袋", "低脂"],
      defaultRequirement: "",
      personalizedRecipe: {},
    };
  }
}

function normalizeAssetPaths(value) {
  if (typeof value === "string") return value.replace(/^\/assets\//, `${AS}/`);
  if (Array.isArray(value)) return value.map(normalizeAssetPaths);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalizeAssetPaths(item)]));
  }
  return value;
}

function render() {
  if (!state.data) return;
  document.body.style.overflow = state.stage === "detected" ? "hidden" : "";

  const views = {
    watching: renderVideoScreen,
    detected: renderVideoScreen,
    analyzing: renderAnalysisScreen,
    customizing: renderCustomizeScreen,
    generating: renderGeneratingScreen,
    result: renderResultScreen,
  };
  app.innerHTML = views[state.stage]();
  bindEvents();
  syncStepOverlayScroll();
}

function bindEvents() {
  app.querySelectorAll("[data-action]").forEach((node) => {
    node.addEventListener("click", handleAction);
  });

  const video = app.querySelector("#demo-video");
  bindVideo(video);

  const textarea = app.querySelector("#requirement");
  if (textarea) {
    textarea.addEventListener("input", (event) => {
      state.requirementText = event.target.value.slice(0, 200);
      state.formError = "";
      const counter = app.querySelector(".counter");
      if (counter) counter.textContent = `${state.requirementText.length}/200`;
    });
  }
}

function handleAction(event) {
  const action = event.currentTarget.dataset.action;
  const value = event.currentTarget.dataset.value;
  if (action === "noop") {
    event.stopPropagation();
    return;
  }

  if (action === "continue") continueWatching();
  if (action === "make") startAnalysis();
  if (action === "drawer") { state.showDrawer = true; render(); }
  if (action === "close-drawer") { state.showDrawer = false; render(); }
  if (action === "tag") toggleTag(value);
  if (action === "mic") startVoiceInput();
  if (action === "submit") submitRequirements();
  if (action === "tab") { state.activeTab = value; render(); }
  if (action === "open-step") { state.stepOverlayIndex = Number(value) || 0; render(); }
  if (action === "close-steps") { state.stepOverlayIndex = null; render(); }
  if (action === "modify") { state.stage = "customizing"; render(); }
  if (action === "restart") resetToVideo();
  if (action === "save") showToast("配方已保存到演示列表");
  if (action === "debug") { state.stage = value; render(); if (value === "analyzing") startAnalysis(); if (value === "generating") startGeneration(); }
}

function bindVideo(video) {
  if (video) {
    video.addEventListener("error", () => {
      state.videoError = true;
      render();
    }, { once: true });

    video.addEventListener("play", () => {
      state.isPlaying = true;
      setPlayHint(false);
    });

    video.addEventListener("pause", () => {
      state.isPlaying = false;
      setPlayHint(true);
      if (state.userPauseIntent) {
        state.userPauseIntent = false;
        // Capture frame immediately while video element is still valid
        let frameDataUrl = "";
        let imageBase64 = "";
        try {
          if (video.videoWidth > 0 && video.videoHeight > 0) {
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext("2d").drawImage(video, 0, 0);
            frameDataUrl = canvas.toDataURL("image/jpeg", 0.85);
            imageBase64 = frameDataUrl.split(",")[1] || "";
          }
        } catch (e) { console.warn("Frame capture failed:", e); }
        state.pauseFrame = frameDataUrl;
        state.pauseFrameBase64 = imageBase64;
        state.stage = "detected";
        state.identifyResult = null;
        render();
        // Now call API with already-captured frame
        callIdentifyApi(imageBase64);
      }
    });

    video.addEventListener("ended", () => {
      state.userPauseIntent = false;
      state.isPlaying = false;
      setPlayHint(true);
    });
  }

  app.querySelector(".video-hit")?.addEventListener("click", () => {
    if (state.stage !== "watching") return;
    if (state.videoError || !getVideoUrl()) {
      identifyFrame(null);
      return;
    }
    if (video.paused) {
      video.play().catch(() => setPlayHint(true));
    } else {
      state.userPauseIntent = true;
      video.pause();
    }
  });
}

function setPlayHint(show) {
  const hint = app.querySelector(".play-hint");
  if (hint) hint.hidden = !show;
}

function continueWatching() {
  state.stage = "watching";
  render();
  const video = app.querySelector("#demo-video");
  video?.play?.().catch(() => {});
}

async function identifyFrame(videoEl) {
  // Legacy path for fallback click (no video available)
  state.stage = "detected";
  state.identifyResult = null;
  state.pauseFrame = "";
  state.pauseFrameBase64 = "";
  render();
  await callIdentifyApi("");
}

async function callIdentifyApi(imageBase64) {
  try {
    const resp = await fetch("/api/identify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_base64: imageBase64,
        video_id: state.data.currentVideo.id,
        title: state.data.currentVideo.title || "",
      }),
    });
    if (resp.ok) {
      state.identifyResult = await resp.json();
      state.data.currentVideo.category = state.identifyResult.dish_name || state.data.currentVideo.category;
    }
  } catch (e) { console.warn("Identify API error:", e); }
  render();
}

function resetToVideo() {
  cancelWork();
  state.stage = "watching";
  state.analysis = { progress: 0, steps: [] };
  state.generation = { progress: 0, message: "" };
  render();
}

async function startAnalysis() {
  cancelWork();
  state.stage = "analyzing";
  const dishName = state.identifyResult?.dish_name || state.data.currentVideo.category || "甜品";
  const dynamicSteps = [
    { id: "identify", label: "识别视频主体", detail: `已识别：${dishName}`, durationMs: 900 },
    { id: "retrieve", label: "检索同类教程", detail: `正在搜索${dishName}相关教程`, durationMs: 1200 },
    { id: "extract", label: "提取配方与步骤", detail: "材料、步骤、温度、时间", durationMs: 1300 },
    { id: "comments", label: "分析评论区反馈", detail: "成功经验、失败原因、常见问题", durationMs: 1400 },
    { id: "synthesize", label: "综合生成基础配方", detail: `正在生成${dishName}基础配方`, durationMs: 1700 },
  ];
  state.analysis = {
    progress: 0,
    steps: dynamicSteps.map((step) => ({ ...step, status: "pending" })),
  };
  render();

  try {
    // Start progress animation while waiting for API
    let animDone = false;
    (async () => {
      const steps = state.analysis.steps;
      // Phase 1: step-by-step animation (each step ~8s to match real AI time)
      for (let i = 0; i < steps.length && !animDone; i++) {
        state.analysis.steps = steps.map((s, idx) => ({
          ...s,
          status: idx < i ? "done" : idx === i ? "active" : "pending",
        }));
        state.analysis.progress = Math.min(85, Math.round(((i + 0.5) / steps.length) * 85));
        updateAnalysisDom();
        // Each step takes longer to match real AI processing (~15-20s per step)
        const stepTime = 12000 + Math.random() * 6000;
        const interval = 500;
        for (let t = 0; t < stepTime && !animDone; t += interval) {
          await sleep(interval);
          const subProgress = Math.min(85, Math.round(((i + t / stepTime) / steps.length) * 85));
          state.analysis.progress = subProgress;
          updateAnalysisDom();
        }
      }
      // Phase 2: slow crawl from 85% to 95% while still waiting
      let p = 86;
      while (!animDone && p < 95) {
        state.analysis.progress = p;
        state.analysis.steps = state.analysis.steps.map(s => ({ ...s, status: "done" }));
        updateAnalysisDom();
        await sleep(2000);
        p++;
      }
    })();

    const result = await runTaskWithFallback({
      startUrl: "/api/analyze/start",
      statusUrl: (taskId) => `/api/analyze/status/${taskId}`,
      simpleUrl: "/api/analyze",
      body: { video_id: state.data.currentVideo.id, category_key: state.identifyResult?.category_key || "", use_ai: true },
      onProgress: applyAnalysisStatus,
      fallback: runDemoAnalysis,
      fallbackMessage: "Analyze API unavailable, switched to demo fallback.",
      timeoutMs: 120000,
    });
    animDone = true;
    if (result?.baseRecipe || result?.base_recipe) state.baseRecipe = result.baseRecipe || result.base_recipe;
    if (result?.comment_summary) state.commentInsights = result.comment_summary;
    state.analysis.steps = state.analysis.steps.map(s => ({ ...s, status: "done" }));
    state.analysis.progress = 100;
    updateAnalysisDom();
  } finally {
    setTimer(() => {
      state.stage = "customizing";
      render();
    }, 400);
  }
}

async function runDemoAnalysis() {
  const steps = state.analysis.steps;
  let elapsed = 0;
  const total = steps.reduce((sum, step) => sum + (step.durationMs || 900), 0);
  for (let i = 0; i < steps.length; i += 1) {
    state.analysis.steps = steps.map((step, index) => ({
      ...step,
      status: index < i ? "done" : index === i ? "active" : "pending",
    }));
    updateAnalysisDom();
    await sleep(steps[i].durationMs || 900);
    elapsed += steps[i].durationMs || 900;
    state.analysis.progress = Math.min(96, Math.round((elapsed / total) * 100));
    updateAnalysisDom();
  }
  state.analysis.steps = steps.map((step) => ({ ...step, status: "done" }));
  state.analysis.progress = 100;
  state.baseRecipe = state.data.baseRecipe;
  updateAnalysisDom();
  return { baseRecipe: state.data.baseRecipe };
}

function applyAnalysisStatus(payload) {
  if (!payload || typeof payload !== "object") throw new Error("Invalid analyze status");
  state.analysis.progress = Math.max(0, Math.min(100, Number(payload.progress || 0)));
  if (Array.isArray(payload.steps)) {
    state.analysis.steps = payload.steps.map((step) => ({ ...step, status: step.status || "pending" }));
  } else if (payload.currentStep) {
    const ids = state.data.analysisSteps.map((step) => step.id);
    const activeIndex = ids.indexOf(payload.currentStep);
    state.analysis.steps = state.data.analysisSteps.map((step, index) => ({
      ...step,
      status: index < activeIndex ? "done" : index === activeIndex ? "active" : "pending",
    }));
  }
  updateAnalysisDom();
}

function updateAnalysisDom() {
  if (state.stage !== "analyzing") return;
  const ring = app.querySelector(".progress-ring");
  if (ring) {
    ring.style.setProperty("--progress", state.analysis.progress);
    ring.dataset.progress = `${state.analysis.progress}%`;
  }
  const list = app.querySelector(".step-list");
  if (list) list.innerHTML = state.analysis.steps.map(renderAnalysisStep).join("");
}

function toggleTag(tag) {
  if (state.selectedTags.has(tag)) state.selectedTags.delete(tag);
  else state.selectedTags.add(tag);
  state.formError = "";
  render();
}

let activeRecognition = null;

function startVoiceInput() {
  // If already recording, stop
  if (activeRecognition) {
    activeRecognition.stop();
    activeRecognition = null;
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showToast("当前浏览器不支持语音输入，请使用 Chrome");
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.continuous = true;
  recognition.interimResults = true;
  activeRecognition = recognition;

  showToast("🎤 录音中…再按一次结束");
  const micBtn = app.querySelector(".mic-btn");
  if (micBtn) micBtn.style.background = "#ef3f37";

  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    state.requirementText = transcript;
    const textarea = app.querySelector("#requirement");
    if (textarea) textarea.value = transcript;
    const counter = app.querySelector(".counter");
    if (counter) counter.textContent = `${transcript.length}/200`;
  };

  recognition.onend = () => {
    activeRecognition = null;
    if (micBtn) micBtn.style.background = "";
    showToast("语音输入完成");
  };

  recognition.onerror = (event) => {
    activeRecognition = null;
    if (micBtn) micBtn.style.background = "";
    if (event.error === "not-allowed") {
      showToast("请允许麦克风权限");
    } else if (event.error !== "aborted") {
      showToast("语音识别失败，请重试");
    }
  };

  recognition.start();
}

function submitRequirements() {
  if (state.submitting) return;
  const text = state.requirementText.trim();
  if (!text && state.selectedTags.size === 0) {
    state.formError = "请选择标签或输入你的需求";
    render();
    return;
  }
  state.submitting = true;
  state.stage = "generating";
  render();
  startGeneration();
}

async function startGeneration() {
  cancelWork();
  state.generation = { progress: 4, message: "正在整合个性化需求" };
  render();

  try {
    const result = await runTaskWithFallback({
      startUrl: "/api/generate-recipe/start",
      statusUrl: (taskId) => `/api/generate-recipe/status/${taskId}`,
      simpleUrl: "/api/generate-recipe",
      body: {
        category_key: state.identifyResult?.category_key || "",
        base_recipe: state.baseRecipe,
        user_requirement: [...state.selectedTags, state.requirementText.trim()].filter(Boolean).join("，"),
        comment_insights: state.commentInsights,
        use_ai: true,
      },
      onProgress: applyGenerationStatus,
      fallback: runDemoGeneration,
      timeoutMs: 120000,
    });
    state.personalizedRecipe = enrichRecipe(result || state.data.personalizedRecipe, state.baseRecipe);
  } finally {
    state.submitting = false;
    state.generation.progress = 100;
    updateGenerationDom();
    setTimer(() => {
      state.stage = "result";
      render();
    }, 300);
  }
}

async function runDemoGeneration() {
  const messages = ["正在整合个性化需求", "正在调整材料与用量", "正在适配空气炸锅", "正在整理步骤图和避坑建议"];
  const total = 3300;
  const started = performance.now();
  while (performance.now() - started < total) {
    const ratio = (performance.now() - started) / total;
    state.generation.progress = Math.min(94, Math.round(6 + ratio * 88));
    state.generation.message = messages[Math.min(messages.length - 1, Math.floor(ratio * messages.length))];
    updateGenerationDom();
    await sleep(260);
  }
  state.generation.progress = 99;
  state.generation.message = "正在完成图文配方";
  updateGenerationDom();
  return state.data.personalizedRecipe;
}

function applyGenerationStatus(payload) {
  if (!payload || typeof payload !== "object") throw new Error("Invalid generation status");
  state.generation.progress = Math.min(99, Math.max(0, Number(payload.progress || 0)));
  state.generation.message = payload.currentMessage || state.generation.message;
  updateGenerationDom();
}

function updateGenerationDom() {
  if (state.stage !== "generating") return;
  const fill = app.querySelector(".progress-fill");
  if (fill) fill.style.setProperty("--progress", `${state.generation.progress}%`);
  const message = app.querySelector(".gen-message");
  if (message) message.textContent = state.generation.message || "正在整合个性化需求";
}

async function runTaskWithFallback(config) {
  try {
    const start = await request(config.startUrl, jsonPost(config.body), config.timeoutMs);
    if (!start?.taskId) throw new Error("No task id");
    while (true) {
      await sleep(700);
      const status = await request(config.statusUrl(start.taskId), {}, config.timeoutMs);
      config.onProgress(status);
      if (status.status === "done") return status.result;
      if (status.status === "error") throw new Error("Task error");
    }
  } catch {
    try {
      const simple = await request(config.simpleUrl, jsonPost(config.body), config.timeoutMs);
      if (simple?.result) return simple.result;
      if (simple?.baseRecipe || simple?.title) return simple;
      throw new Error("Simple endpoint returned no result");
    } catch {
      if (config.fallbackMessage && isDev) console.info(config.fallbackMessage);
      return config.fallback();
    }
  }
}

function jsonPost(body) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

async function request(url, options = {}, timeoutMs = 120000) {
  const controller = new AbortController();
  state.controllers.add(controller);
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error("Request failed");
    return await response.json();
  } finally {
    clearTimeout(timer);
    state.controllers.delete(controller);
  }
}

function renderVideoScreen() {
  const video = state.data.currentVideo;
  const stats = video.stats || {};
  const videoUrl = getVideoUrl();
  const identifying = state.stage === "detected" && !state.identifyResult;
  const dishName = state.identifyResult?.dish_name || video.category || "甜品";
  const modal = state.stage === "detected" ? `
    <div class="modal-backdrop">
      <section class="detect-modal" role="dialog" aria-modal="true" aria-labelledby="detect-title">
        <button class="modal-close" data-action="continue" aria-label="关闭识别弹窗">×</button>
        ${identifying ? `
          <h2 id="detect-title">AI 正在识别画面…</h2>
          <p>正在分析当前视频帧内容</p>
        ` : `
          <h2 id="detect-title">识别到你正在看<br><span class="subject">${escapeHtml(dishName)}</span></h2>
          ${state.identifyResult?.reason ? `<p style="font-size:13px;color:#888;margin-bottom:8px">置信度 ${Math.round((state.identifyResult.confidence||0)*100)}% · ${escapeHtml(state.identifyResult.reason)}</p>` : ""}
          <p>想做同款？AI 将结合多个同类教程和评论区反馈，为你定制更适合你的配方。</p>
          <div class="modal-actions">
            <button class="primary-btn" data-action="make">我想做同款</button>
            <button class="secondary-btn" data-action="continue">继续观看</button>
          </div>
        `}
      </section>
    </div>` : "";

  return `
    <section class="screen video-screen">
      ${videoUrl && !state.videoError ? `<video id="demo-video" class="video-media" playsinline preload="metadata" crossorigin="anonymous" poster="${state.stage === "detected" && state.pauseFrame ? state.pauseFrame : video.poster}" src="${escapeAttr(videoUrl)}"></video>` : `<div class="video-fallback" aria-label="视频封面"></div>`}
      <button class="video-hit" aria-label="播放或暂停视频" style="position:absolute;inset:0;z-index:2;background:transparent"></button>
      <div class="video-shade"></div>
      ${statusBar()}
      <div class="feed-tabs"><span>关注</span><span>推荐</span></div>
      <button class="icon-btn search-btn" aria-label="搜索"><img src="${AS}/icons/mobile-ui/search_white.png" alt=""></button>
      <div class="play-hint" ${state.isPlaying ? "hidden" : ""}><img src="${AS}/icons/controls/play.png" alt=""></div>
      <aside class="action-rail">
        <div class="avatar" aria-label="作者头像"></div>
        ${rail(`${AS}/icons/mobile-ui/heart_white.png`, stats.likes || "12.3w", "点赞")}
        ${rail(`${AS}/icons/mobile-ui/comment_white.png`, stats.comments || "3421", "评论")}
        ${rail(`${AS}/icons/mobile-ui/favorite_white.png`, stats.favorites || "9.8w", "收藏")}
        ${rail(`${AS}/icons/mobile-ui/share_white.png`, stats.shares || "2.1w", "分享")}
        <img class="disc" src="${AS}/icons/mobile-ui/sound_disc.png" alt="音乐唱片">
      </aside>
      <div class="video-copy">
        <div class="author">${escapeHtml(video.author)}</div>
        <h1 class="video-title">${escapeHtml(video.title)}</h1>
        <p class="video-desc">暂停视频，让 AI 识别教程主体并生成更适合你的做法。</p>
        <p class="music">♪ 原声 · 酥皮泡芙烘焙教程</p>
      </div>
      <nav class="bottom-nav" aria-label="底部导航">
        ${nav("home_white.png", "首页")}
        ${nav("friends_white.png", "朋友")}
        <div class="nav-item"><img class="create" src="${AS}/icons/mobile-ui/create_plus.png" alt=""><span>发布</span></div>
        ${nav("message_white.png", "消息")}
        ${nav("profile_white.png", "我的")}
      </nav>
      ${debugControls()}
      ${modal}
    </section>`;
}

function renderAnalysisScreen() {
  return `
    <section class="screen analysis-screen">
      ${statusBar()}
      <div class="analysis-hero">
        <h1>AI 正在为你分析…</h1>
        <p>从视频、教程和评论里提取可执行方案</p>
        <img class="cloud-left" src="${AS}/icons/decor/cloud.png" alt="">
        <img class="cloud-right" src="${AS}/icons/decor/cloud.png" alt="">
        <img class="team" src="${AS}/illustrations/delivery_scene.png" alt="厨师团队正在制作甜点">
        <img class="city" src="${AS}/backgrounds/city_cloud_layer.png" alt="">
      </div>
      <section class="analysis-card">
        <div class="analysis-head">
          <div>
            <strong>处理进度</strong>
            <div class="step-detail">自动检索、抽取并综合基础配方</div>
          </div>
          <div class="progress-ring" style="--progress:${state.analysis.progress}" data-progress="${state.analysis.progress}%"></div>
        </div>
        <div class="step-list">
          ${state.analysis.steps.map(renderAnalysisStep).join("")}
        </div>
      </section>
    </section>`;
}

function renderAnalysisStep(step) {
  const status = step.status || "pending";
  const marker = status === "done" ? "✓" : status === "error" ? "!" : "";
  return `
    <div class="step-row ${status}">
      <div class="step-icon">${marker}</div>
      <div>
        <div class="step-title">${escapeHtml(step.label)}</div>
        <div class="step-detail">${escapeHtml(status === "active" ? "处理中…" : step.detail || "等待处理")}</div>
      </div>
    </div>`;
}

function renderCustomizeScreen() {
  const recipe = state.baseRecipe || state.data.baseRecipe;
  const dishName = state.identifyResult?.dish_name || state.data.currentVideo.category || "甜品";
  return `
    <section class="screen custom-screen">
      <header class="custom-header">
        <h1>定制你的同款${escapeHtml(dishName)}</h1>
        <p>AI 已综合多个教程和评论区生成基础配方</p>
      </header>
      <section class="base-card">
        <img src="${state.pauseFrame ? state.pauseFrame : `${AS}/food/pastry_card_photo@2x.png`}" alt="视频截帧">
        <div>
          <h2>${escapeHtml(recipe.title || `${dishName}基础配方`)}</h2>
          <div class="metrics">
            <div class="metric"><strong>${(recipe.ingredients || []).length}</strong>材料</div>
            <div class="metric"><strong>${(recipe.steps || []).length}</strong>步骤</div>
            <div class="metric"><strong>${recipe.success_rate || "92%"}</strong>成功率</div>
          </div>
          <button class="small-btn" data-action="drawer">查看详情</button>
        </div>
      </section>
      <section class="require-card">
        <h2 class="section-title">个性化需求</h2>
        <div class="tag-grid">
          ${state.data.requirementTags.map((tag) => `<button class="tag ${state.selectedTags.has(tag) ? "selected" : ""}" data-action="tag" data-value="${escapeAttr(tag)}">${escapeHtml(tag)}</button>`).join("")}
        </div>
        <label class="textarea-wrap">
          <textarea id="requirement" maxlength="200" placeholder="例如：少糖、用空气炸锅、没有裱花袋，希望新手友好">${escapeHtml(state.requirementText)}</textarea>
          <span class="counter">${state.requirementText.length}/200</span>
        </label>
        <div class="form-actions">
          <button class="mic-btn" data-action="mic" aria-label="语音输入"><img src="${AS}/icons/controls/microphone.png" alt=""></button>
          <button class="primary-btn" data-action="submit">${state.submitting ? "提交中…" : "生成个性化配方"}</button>
        </div>
        <p class="error-text">${escapeHtml(state.formError)}</p>
      </section>
      ${state.showDrawer ? renderDrawer(recipe) : ""}
    </section>`;
}

function renderDrawer(recipe) {
  const dishName = state.identifyResult?.dish_name || "甜品";
  const ingredients = recipe.ingredients || [];
  const steps = recipe.steps || [];
  const pitfalls = recipe.common_pitfalls || recipe.pitfalls || [];
  const tools = recipe.tools || [];
  const faq = recipe.faq || [];
  return `
    <div class="drawer-backdrop">
      <section class="drawer-panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <button class="modal-close" data-action="close-drawer" aria-label="关闭详情">×</button>
        <h2 id="drawer-title">${escapeHtml(recipe.title || `${dishName}基础配方`)}</h2>
        ${recipe.summary ? `<p>${escapeHtml(recipe.summary)}</p>` : ""}
        ${recipe.serving ? `<p><strong>份量：</strong>${escapeHtml(recipe.serving)}</p>` : ""}
        ${recipe.difficulty ? `<p><strong>难度：</strong>${escapeHtml(recipe.difficulty)}</p>` : ""}
        <h3>材料清单（${ingredients.length} 种）</h3>
        <ul>${ingredients.map((item) => `<li><strong>${escapeHtml(item.name)}</strong> ${escapeHtml(item.amount || "")}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</li>`).join("")}</ul>
        ${tools.length ? `<h3>工具</h3><ul>${tools.map((t) => `<li>${escapeHtml(typeof t === "string" ? t : t.name || "")}</li>`).join("")}</ul>` : ""}
        <h3>步骤（${steps.length} 步）</h3>
        <ul>${steps.map((s) => `<li><strong>${escapeHtml(s.title || `步骤${s.step || ""}`)}</strong>：${escapeHtml(s.action || "")}${s.key_state ? ` · 状态：${escapeHtml(s.key_state)}` : ""}</li>`).join("")}</ul>
        ${pitfalls.length ? `<h3>避坑提示</h3><ul>${pitfalls.map((p) => typeof p === "string" ? `<li>${escapeHtml(p)}</li>` : `<li><strong>${escapeHtml(p.problem || "")}</strong>：${escapeHtml(p.solution || p.reason || "")}</li>`).join("")}</ul>` : ""}
        ${faq.length ? `<h3>常见问题</h3><ul>${faq.map((f) => `<li><strong>${escapeHtml(f.question || "")}</strong>：${escapeHtml(f.answer || "")}</li>`).join("")}</ul>` : ""}
        ${recipe.evidence_videos ? `<p style="font-size:12px;color:#999;margin-top:16px">数据来源：${recipe.evidence_videos.length} 个教程视频 + 评论区洞察</p>` : ""}
      </section>
    </div>`;
}

function renderGeneratingScreen() {
  return `
    <section class="screen generating-screen">
      ${statusBar()}
      <div class="gen-stage">
        <div class="orbit" aria-hidden="true">
          <img class="chef" src="${AS}/illustrations/chef_mixing.png" alt="">
          ${orbiter(`${AS}/icons/decor/chef_hat.png`, 0, "0s")}
          ${orbiter(`${AS}/icons/decor/whisk_line.png`, 90, "-2s")}
          ${orbiter(`${AS}/icons/decor/clipboard.png`, 180, "-4s")}
          ${orbiter(`${AS}/icons/decor/star.png`, 270, "-6s")}
        </div>
        <h1 class="gen-title">AI 生成中…</h1>
        <p class="gen-subtitle">正在为你生成个性化配方，请稍候</p>
        <div class="progress-bar" aria-label="生成进度"><div class="progress-fill" style="--progress:${state.generation.progress}%"></div></div>
        <div class="gen-message">${escapeHtml(state.generation.message || "正在整合个性化需求")}</div>
      </div>
    </section>`;
}

function renderResultScreen() {
  const recipe = state.personalizedRecipe;
  return `
    <section class="screen scroll-screen result-screen">
      <header class="result-header">
        <h1>你的个性化配方已完成！</h1>
        <div class="tabs">
          ${tab("recipe", "配方")}
          ${tab("steps", "步骤")}
          ${tab("pitfalls", "避坑指南")}
          ${tab("tips", "小贴士")}
        </div>
      </header>
      <section id="recipe" class="result-card">
        <h2>${escapeHtml(recipe.title)}</h2>
        <p>${escapeHtml(recipe.summary)}</p>
        <button class="small-btn" data-action="save">保存配方</button>
        <img class="hero-food" src="${state.pauseFrame || `${AS}/food/pastry_result_photo.png`}" alt="配方成品">
        <div class="adjustments">${recipe.adjustments.map((item) => `<div class="adjustment">✓ ${escapeHtml(item)}</div>`).join("")}</div>
      </section>
      <section class="result-card">
        <h2>材料清单</h2>
        <div class="ingredient-grid">${recipe.ingredients.map(renderIngredient).join("")}</div>
      </section>
      <section class="result-card">
        <h2>工具推荐</h2>
        <div class="tool-row">${recipe.tools.map(renderTool).join("")}</div>
      </section>
      <section id="steps" class="result-card">
        <h2>步骤图文</h2>
        <div class="step-scroller">${recipe.steps.map(renderRecipeStep).join("")}</div>
      </section>
      <section id="pitfalls" class="result-card">
        <h2>避坑指南</h2>
        ${recipe.pitfalls.map((item) => `<div class="pitfall"><strong>${escapeHtml(item.problem)}</strong><p>${escapeHtml(item.reason)}</p><p>${escapeHtml(item.solution)}</p></div>`).join("")}
      </section>
      <section id="tips" class="result-card">
        <h2>FAQ</h2>
        ${recipe.faq.map((item) => `<div class="faq"><strong>${escapeHtml(item.question)}</strong><p>${escapeHtml(item.answer)}</p></div>`).join("")}
      </section>
      <div class="result-actions">
        <button class="primary-btn" data-action="save">保存配方</button>
        <button class="secondary-btn" data-action="modify">修改我的需求</button>
      </div>
      <button class="secondary-btn" data-action="restart" style="width:100%">重新看视频</button>
    </section>
    ${state.stepOverlayIndex !== null ? renderStepOverlay(recipe) : ""}`;
}

function renderIngredient(item) {
  const label = item.type === "adjusted" ? "已调整" : item.type === "substitute" ? "可替代" : "必需";
  return `<div class="ingredient"><strong>${escapeHtml(item.name)} ${escapeHtml(item.amount)}</strong><span class="note">${escapeHtml(label)}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</span></div>`;
}

function renderTool(name) {
  const icon = name.includes("打蛋") ? "whisk.png" : name.includes("刮刀") ? "spatula.png" : name.includes("锅") ? "pot.png" : "oven.png";
  return `<div class="tool-chip"><img src="${AS}/icons/tools/${icon}" alt=""><span>${escapeHtml(name)}</span></div>`;
}

function renderRecipeStep(step, index) {
  const img = step.image || state.pauseFrame || "";
  return `
    <article class="recipe-step">
      ${img ? `<button class="step-open" data-action="open-step" data-value="${index}" aria-label="查看第 ${step.step} 步详情">
        <img src="${escapeAttr(img)}" alt="${escapeAttr(step.title)}">
      </button>` : ""}
      <div class="step-body">
        <h3>${step.step}. ${escapeHtml(step.title)}</h3>
        <p>${escapeHtml(step.action || "")}</p>
        <p><strong>时间：</strong>${escapeHtml(step.time || step.temperature || "按状态调整")}</p>
        <p><strong>状态：</strong>${escapeHtml(step.keyState || step.key_state || "观察状态稳定后进入下一步。")}</p>
        <p><strong>风险：</strong>${escapeHtml(step.risk || "注意操作节奏。")}</p>
      </div>
    </article>`;
}

function renderStepOverlay(recipe) {
  return `
    <div class="step-overlay" data-action="close-steps" role="dialog" aria-modal="true" aria-label="步骤图文详情">
      <button class="step-overlay-close" data-action="close-steps" aria-label="关闭步骤详情">关闭</button>
      <div class="step-overlay-track" data-action="noop">
        ${recipe.steps.map(renderFloatingStep).join("")}
      </div>
    </div>`;
}

function renderFloatingStep(step, index) {
  return `
    <article class="floating-step" aria-label="第 ${step.step} 步">
      <div class="floating-image-wrap">
        <img src="${escapeAttr(step.image)}" alt="${escapeAttr(step.title)}">
      </div>
      <div class="floating-step-body">
        <span class="floating-index">${step.step}/${state.personalizedRecipe.steps.length}</span>
        <h2>${step.step}. ${escapeHtml(step.title)}</h2>
        <p>${escapeHtml(step.action || stepDetails[index]?.action || "按提示完成本步骤。")}</p>
        <p><strong>时间：</strong>${escapeHtml(step.time || "按状态调整")}</p>
        <p><strong>关键状态：</strong>${escapeHtml(step.keyState || stepDetails[index]?.keyState || "观察状态稳定后进入下一步。")}</p>
        <p><strong>风险提示：</strong>${escapeHtml(step.risk || stepDetails[index]?.risk || "不要急于升温或加量。")}</p>
      </div>
    </article>`;
}

function syncStepOverlayScroll() {
  if (state.stepOverlayIndex === null) return;
  const track = app.querySelector(".step-overlay-track");
  if (!track) return;
  setTimer(() => {
    const target = track.children[state.stepOverlayIndex];
    target?.scrollIntoView({ behavior: "auto", block: "nearest", inline: "center" });
  }, 0);
}

function enrichRecipe(recipe, baseRecipe) {
  const dishName = state.identifyResult?.dish_name || state.data?.currentVideo?.category || "甜品";
  const baseIngredients = (baseRecipe?.ingredients || recipe?.ingredients || []).map((item) => ({
    ...item,
    type: item.type || "required",
    note: item.note || "",
  }));

  const steps = (recipe?.steps || baseRecipe?.steps || []).map((step) => ({
    ...step,
    keyState: step.keyState || step.key_state || "",
    image: step.image || state.pauseFrame || "",
  }));

  return {
    title: recipe?.title || `${dishName}个性化配方`,
    summary: recipe?.summary || `根据你的需求定制的${dishName}配方`,
    adjustments: recipe?.adjustments || [],
    ingredients: recipe?.ingredients || baseIngredients,
    tools: recipe?.tools || baseRecipe?.tools || [],
    steps,
    pitfalls: recipe?.pitfalls || recipe?.common_pitfalls || baseRecipe?.common_pitfalls || [],
    faq: recipe?.faq || baseRecipe?.faq || [],
  };
}

function getVideoUrl() {
  const fromQuery = new URLSearchParams(location.search).get("video");
  const fromEnv = window.VITE_DEMO_VIDEO_URL || "";
  const fromDemo = state.data?.currentVideo?.videoUrl || "";
  const url = fromQuery || fromEnv || fromDemo;
  return url && !url.includes("REPLACE_WITH") && !url.includes("your-video-url") ? url : "";
}

function statusBar() {
  return `<div class="status-bar"><span>9:41</span><span class="status-icons">▰▰ ◔ 🔋</span></div>`;
}

function rail(icon, text, label) {
  return `<div class="rail-item" aria-label="${label}"><img src="${icon}" alt=""><span>${escapeHtml(text)}</span></div>`;
}

function nav(icon, label) {
  return `<div class="nav-item"><img src="${AS}/icons/mobile-ui/${icon}" alt=""><span>${label}</span></div>`;
}

function orbiter(src, angle, delay) {
  return `<div class="orbiter" style="--a:${angle}deg;--d:${delay}"><img src="${src}" alt=""></div>`;
}

function tab(id, label) {
  return `<button class="tab ${state.activeTab === id ? "active" : ""}" data-action="tab" data-value="${id}">${label}</button>`;
}

function debugControls() {
  if (!isDev || !showDebugControls) return "";
  return `<div class="debug" aria-label="调试跳转">
    ${["watching", "analyzing", "customizing", "generating", "result"].map((stage) => `<button data-action="debug" data-value="${stage}">${stage}</button>`).join("")}
  </div>`;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  setTimer(() => toast.classList.remove("show"), 1800);
}

function cancelWork() {
  state.controllers.forEach((controller) => controller.abort());
  state.controllers.clear();
  clearTransientTimers();
}

function setTimer(fn, ms) {
  const id = setTimeout(() => {
    state.timers.delete(id);
    fn();
  }, ms);
  state.timers.add(id);
  return id;
}

function clearTransientTimers() {
  state.timers.forEach(clearTimeout);
  state.timers.clear();
}

function sleep(ms) {
  return new Promise((resolve) => setTimer(resolve, ms));
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function escapeAttr(value = "") {
  return escapeHtml(value);
}

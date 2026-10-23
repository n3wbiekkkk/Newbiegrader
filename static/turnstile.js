/* Bot verification only gates email-code requests; existing auth handlers own identity. */
(() => {
  const row = document.getElementById("auth-bot-row");
  const status = document.getElementById("auth-bot-status");
  let configPromise, scriptPromise, widgetId, token = "", pending;
  let visible = false;
  const unavailable = "ระบบตรวจสอบผู้ใช้งานยังไม่พร้อม กรุณาลองอีกครั้ง";

  function message(text, bad = false) {
    status.textContent = text;
    status.classList.toggle("bad", bad);
  }

  function config() {
    if (!configPromise) {
      configPromise = fetch((window.GRADER_API_BASE || "") + "/api/auth/bot-config", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000),
      }).then(async response => {
        if (response.status === 404 && ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
          return { enabled: false };
        }
        if (!response.ok) throw new Error(unavailable);
        const value = await response.json();
        if (typeof value.enabled !== "boolean" || (value.enabled &&
            (typeof value.sitekey !== "string" || !value.sitekey))) throw new Error(unavailable);
        // Re-read a disabled flag at submission time during a staged rollout.
        if (!value.enabled) configPromise = null;
        return value;
      }).catch(error => { configPromise = null; throw error; });
    }
    return configPromise;
  }

  function loadScript() {
    if (typeof window.turnstile?.render === "function") return Promise.resolve();
    if (!scriptPromise) {
      scriptPromise = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        script.async = true;
        const timer = setTimeout(() => reject(new Error(unavailable)), 10000);
        script.onload = () => {
          clearTimeout(timer);
          if (typeof window.turnstile?.render === "function") resolve();
          else reject(new Error(unavailable));
        };
        script.onerror = () => { clearTimeout(timer); reject(new Error(unavailable)); };
        document.head.appendChild(script);
      }).catch(error => { scriptPromise = null; throw error; });
    }
    return scriptPromise;
  }

  async function ensureWidget() {
    const settings = await config();
    if (!settings.enabled) { row.classList.add("hidden"); return false; }
    row.classList.toggle("hidden", !visible);
    await loadScript();
    if (widgetId === undefined) {
      widgetId = window.turnstile.render("#auth-turnstile", {
        sitekey: settings.sitekey, action: "email_request", theme: "auto", size: "flexible",
        callback(value) {
          token = value;
          message("ตรวจสอบผู้ใช้งานแล้ว");
          pending?.resolve(value);
        },
        "expired-callback"() { token = ""; message("กรุณาตรวจสอบผู้ใช้งานอีกครั้ง"); },
        "error-callback"() {
          token = ""; message(unavailable, true);
          pending?.reject(new Error(unavailable));
          return true;
        },
      });
    }
    return true;
  }

  window.GraderBotVerification = {
    async prepare(needed) {
      visible = !!needed;
      row.classList.toggle("hidden", !visible);
      if (!needed) return;
      try { await ensureWidget(); }
      catch { message(unavailable, true); }
    },
    async token() {
      visible = true;
      if (!await ensureWidget()) return null;
      if (token) return token;
      message("กรุณายืนยันว่าเป็นผู้ใช้งานจริงด้านล่าง");
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending = null;
          reject(new Error("ตรวจสอบผู้ใช้งานไม่สำเร็จ กรุณาลองอีกครั้ง"));
        }, 30000);
        pending = {
          resolve(value) { clearTimeout(timer); pending = null; resolve(value); },
          reject(error) { clearTimeout(timer); pending = null; reject(error); },
        };
      });
    },
    reset() {
      token = "";
      if (widgetId !== undefined) window.turnstile.reset(widgetId);
    },
  };
})();

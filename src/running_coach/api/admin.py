"""관리자 API와 단일 LLM 설정 페이지."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import HTMLResponse

from ..models.llm_settings import (
    AdminLLMSettingsPatch,
    LLMSettings,
    UserLLMSettings,
    UserLLMSettingsPatch,
)
from ..storage.admin_settings import AdminSettingsService


def create_admin_router(
    admin_settings: AdminSettingsService,
    admin_api_key: Optional[str],
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    def require_admin(
        authorization: Annotated[Optional[str], Header()] = None,
        x_admin_api_key: Annotated[Optional[str], Header(alias="X-Admin-API-Key")] = None,
    ) -> None:
        if not admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin API key is not configured",
            )

        token = x_admin_api_key
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()

        if token != admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin API key",
            )

    @router.get("", response_class=HTMLResponse)
    def admin_page() -> str:
        return _admin_html()

    @router.get("/llm-settings", dependencies=[Depends(require_admin)])
    def get_llm_settings() -> dict[str, str]:
        return _settings_payload(admin_settings.get_global_llm_settings())

    @router.patch("/llm-settings", dependencies=[Depends(require_admin)])
    def patch_llm_settings(
        patch: AdminLLMSettingsPatch,
    ) -> dict[str, str]:
        return _settings_payload(admin_settings.update_global_llm_settings(patch))

    @router.get("/users/{user_id}/llm-settings", dependencies=[Depends(require_admin)])
    def get_user_llm_settings(user_id: str) -> dict[str, object]:
        return _user_settings_payload(admin_settings.get_user_llm_settings(user_id))

    @router.patch("/users/{user_id}/llm-settings", dependencies=[Depends(require_admin)])
    def patch_user_llm_settings(
        user_id: str,
        patch: UserLLMSettingsPatch,
    ) -> dict[str, object]:
        return _user_settings_payload(admin_settings.update_user_llm_settings(user_id, patch))

    return router


def _settings_payload(settings: LLMSettings) -> dict[str, str]:
    return {
        "plannerMode": settings.planner_mode,
        "llmProvider": settings.llm_provider,
        "llmModel": settings.llm_model,
    }


def _user_settings_payload(user_settings: UserLLMSettings) -> dict[str, object]:
    return {
        "userId": user_settings.user_id,
        "overrides": {
            "plannerMode": user_settings.override_planner_mode,
            "llmProvider": user_settings.override_llm_provider,
            "llmModel": user_settings.override_llm_model,
        },
        "effective": _settings_payload(user_settings.effective),
    }


def _admin_html() -> str:
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Running Coach Admin</title>
  <style>
    :root { color-scheme: light; font-family: Inter, system-ui, -apple-system, sans-serif; }
    body { margin: 0; background: #f6f7f8; color: #1d2329; }
    main { max-width: 1120px; margin: 0 auto; padding: 32px 20px 48px; }
    header { display: flex; justify-content: space-between; gap: 20px; align-items: end; }
    h1 { margin: 0; font-size: 28px; font-weight: 720; letter-spacing: 0; }
    h2 { margin: 0 0 16px; font-size: 18px; letter-spacing: 0; }
    label { display: grid; gap: 7px; font-size: 13px; font-weight: 650; }
    input, select {
      width: 100%; box-sizing: border-box; height: 40px; border: 1px solid #c8d0d8;
      border-radius: 6px; padding: 0 10px; background: #fff; font: inherit;
    }
    button {
      height: 40px; border: 0; border-radius: 6px; padding: 0 14px;
      background: #176b55; color: white; font-weight: 700; cursor: pointer;
    }
    button.secondary { background: #38434f; }
    section {
      margin-top: 24px; background: #fff; border: 1px solid #dce1e6;
      border-radius: 8px; padding: 20px;
    }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .auth { min-width: 320px; }
    .actions { display: flex; gap: 10px; align-items: end; margin-top: 16px; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; }
    th, td { text-align: left; border-bottom: 1px solid #e6eaee; padding: 10px 8px; }
    th { font-size: 12px; color: #5d6975; }
    .status { min-height: 20px; margin-top: 14px; color: #51606f; font-size: 13px; }
    @media (max-width: 780px) {
      header, .grid { display: grid; grid-template-columns: 1fr; }
      .auth { min-width: 0; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <h1>LLM Settings</h1>
    <label class="auth">Admin API Key
      <input id="apiKey" type="password" autocomplete="off">
    </label>
  </header>

  <section>
    <h2>Global Default</h2>
    <div class="grid">
      <label>Planner Mode
        <select id="globalPlanner">
          <option value="legacy">legacy</option>
          <option value="llm_driven">llm_driven</option>
        </select>
      </label>
      <label>Provider
        <select id="globalProvider">
          <option value="gemini">gemini</option>
          <option value="openai">openai</option>
          <option value="anthropic">anthropic</option>
        </select>
      </label>
      <label>Model
        <input id="globalModel" placeholder="gemini-3-flash-preview">
      </label>
    </div>
    <div class="actions">
      <button onclick="loadGlobal()">Load</button>
      <button class="secondary" onclick="saveGlobal()">Save</button>
    </div>
  </section>

  <section>
    <h2>User Override</h2>
    <div class="grid">
      <label>User ID
        <input id="userId" placeholder="athlete UUID">
      </label>
      <label>Planner Override
        <select id="userPlanner">
          <option value="">inherit</option>
          <option value="legacy">legacy</option>
          <option value="llm_driven">llm_driven</option>
        </select>
      </label>
      <label>Provider Override
        <select id="userProvider">
          <option value="">inherit</option>
          <option value="gemini">gemini</option>
          <option value="openai">openai</option>
          <option value="anthropic">anthropic</option>
        </select>
      </label>
    </div>
    <div class="grid" style="margin-top:14px">
      <label>Model Override
        <input id="userModel" placeholder="empty = inherit">
      </label>
    </div>
    <div class="actions">
      <button onclick="loadUser()">Load</button>
      <button class="secondary" onclick="saveUser()">Save</button>
    </div>
    <table>
      <thead><tr><th>Scope</th><th>Planner</th><th>Provider</th><th>Model</th></tr></thead>
      <tbody>
        <tr>
          <td>Override</td><td id="overridePlanner"></td>
          <td id="overrideProvider"></td><td id="overrideModel"></td>
        </tr>
        <tr>
          <td>Effective</td><td id="effectivePlanner"></td>
          <td id="effectiveProvider"></td><td id="effectiveModel"></td>
        </tr>
      </tbody>
    </table>
  </section>
  <div class="status" id="status"></div>
</main>
<script>
const apiKey = document.getElementById('apiKey');
apiKey.value = localStorage.getItem('adminApiKey') || '';
apiKey.addEventListener('change', () => localStorage.setItem('adminApiKey', apiKey.value));

function headers() {
  return {'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey.value}`};
}
function setStatus(text) { document.getElementById('status').textContent = text; }
async function request(path, options = {}) {
  const res = await fetch(path, {...options, headers: {...headers(), ...(options.headers || {})}});
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
async function loadGlobal() {
  try {
    const data = await request('/admin/llm-settings');
    globalPlanner.value = data.plannerMode;
    globalProvider.value = data.llmProvider;
    globalModel.value = data.llmModel;
    setStatus('Loaded global settings.');
  } catch (e) { setStatus(e.message); }
}
async function saveGlobal() {
  try {
    await request('/admin/llm-settings', {
      method: 'PATCH',
      body: JSON.stringify({
        plannerMode: globalPlanner.value,
        llmProvider: globalProvider.value,
        llmModel: globalModel.value
      })
    });
    setStatus('Saved global settings.');
  } catch (e) { setStatus(e.message); }
}
function fillUser(data) {
  userPlanner.value = data.overrides.plannerMode || '';
  userProvider.value = data.overrides.llmProvider || '';
  userModel.value = data.overrides.llmModel || '';
  overridePlanner.textContent = data.overrides.plannerMode || 'inherit';
  overrideProvider.textContent = data.overrides.llmProvider || 'inherit';
  overrideModel.textContent = data.overrides.llmModel || 'inherit';
  effectivePlanner.textContent = data.effective.plannerMode;
  effectiveProvider.textContent = data.effective.llmProvider;
  effectiveModel.textContent = data.effective.llmModel;
}
async function loadUser() {
  try {
    fillUser(await request(`/admin/users/${userId.value}/llm-settings`));
    setStatus('Loaded user settings.');
  } catch (e) { setStatus(e.message); }
}
async function saveUser() {
  try {
    fillUser(await request(`/admin/users/${userId.value}/llm-settings`, {
      method: 'PATCH',
      body: JSON.stringify({
        plannerMode: userPlanner.value || null,
        llmProvider: userProvider.value || null,
        llmModel: userModel.value || null
      })
    }));
    setStatus('Saved user settings.');
  } catch (e) { setStatus(e.message); }
}
loadGlobal();
</script>
</body>
</html>
"""

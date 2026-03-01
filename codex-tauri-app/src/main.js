// Tauri API 导入
import { readTextFile, writeTextFile, readDir, mkdir, exists, remove } from '@tauri-apps/plugin-fs';
import { homeDir, join, appDataDir } from '@tauri-apps/api/path';
import { invoke } from '@tauri-apps/api/core';
import { message, ask, confirm } from '@tauri-apps/plugin-dialog';

// 全局状态
let selectedAccount = null;
let accounts = [];
let isLoading = false;
let PATHS = {};
let appSettings = {
    maxLogEntries: 500,
    proxy: {
        proxyUrl: ''
    },
    settingsVersion: 3
};
let appLogs = [];
let logWriteQueue = Promise.resolve();
const MANAGER_KEY = '_manager';
const MANAGER_FIELDS = new Set(['saved_at', 'account_name', 'email', 'account_id', 'plan', MANAGER_KEY]);
const DEFAULT_SETTINGS = {
    maxLogEntries: 500,
    proxy: {
        proxyUrl: ''
    },
    settingsVersion: 3
};

function cloneJson(data) {
    return data === undefined ? undefined : JSON.parse(JSON.stringify(data));
}

// =============================================================================
// 工具函数 - Base64URL 解码 (与 Python base64.b64decode 一致)
// =============================================================================

function base64UrlDecode(str) {
    // 添加padding
    const pad = (4 - (str.length % 4)) % 4;
    const b64 = str.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat(pad);
    
    try {
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return new TextDecoder().decode(bytes);
    } catch (e) {
        console.error('Base64 decode error:', e);
        return null;
    }
}

// =============================================================================
// JWT 解析 (与 Python extract_email_from_token 逻辑一致)
// =============================================================================

function parseJwtPayload(token) {
    if (!token || typeof token !== 'string') return null;
    const parts = token.split('.');
    if (parts.length < 2) return null;
    
    try {
        const payload = base64UrlDecode(parts[1]);
        if (!payload) return null;
        return JSON.parse(payload);
    } catch (e) {
        return null;
    }
}

function extractEmailFromToken(config) {
    if (!config || typeof config !== 'object') return null;

    const manager = config[MANAGER_KEY];
    if (manager?.email) return manager.email;
    if (config.email) return config.email;

    const authConfig = extractStoredAuth(config);
    if (!authConfig.tokens) return null;
    
    // 优先从 id_token 提取
    if (authConfig.tokens.id_token) {
        const payload = parseJwtPayload(authConfig.tokens.id_token);
        if (payload && payload.email) return payload.email;
    }
    
    // 备用：从 access_token 提取
    if (authConfig.tokens.access_token) {
        const payload = parseJwtPayload(authConfig.tokens.access_token);
        if (payload) {
            if (payload.email) return payload.email;
            // OpenAI特定字段
            if (payload['https://api.openai.com/profile']?.email) {
                return payload['https://api.openai.com/profile'].email;
            }
        }
    }
    
    return config.email || null;
}

function extractStoredAuth(config) {
    if (!config || typeof config !== 'object') return {};

    const manager = config[MANAGER_KEY];
    if (manager?.auth_snapshot && typeof manager.auth_snapshot === 'object') {
        return stripManagerFields(manager.auth_snapshot);
    }

    return stripManagerFields(config);
}

function extractAccessToken(config) {
    const authConfig = extractStoredAuth(config);
    const accessToken = authConfig?.tokens?.access_token;
    return typeof accessToken === 'string' && accessToken ? accessToken : null;
}

function getActiveProxyConfig() {
    const proxy = appSettings?.proxy || {};
    return {
        proxyUrl: normalizeProxyUrl(proxy.proxyUrl)
    };
}

function normalizeProxyUrl(value) {
    if (typeof value !== 'string') return '';
    const trimmed = value.trim();
    if (!trimmed) return '';
    return /^[a-z]+:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}

function stripManagerFields(config) {
    if (!config || typeof config !== 'object') return {};

    return Object.fromEntries(
        Object.entries(config)
            .filter(([key]) => !MANAGER_FIELDS.has(key))
            .map(([key, value]) => [key, cloneJson(value)])
    );
}

function extractAccountId(config) {
    if (!config || typeof config !== 'object') return null;

    const manager = config[MANAGER_KEY];
    if (manager?.account_id) return String(manager.account_id);
    if (config.account_id) return String(config.account_id);

    const authConfig = extractStoredAuth(config);
    const tokens = authConfig.tokens || {};

    for (const key of ['account_id', 'chatgpt_account_id', 'user_id']) {
        if (tokens[key]) return String(tokens[key]);
    }

    for (const tokenKey of ['access_token', 'id_token']) {
        const payload = parseJwtPayload(tokens[tokenKey]);
        if (!payload) continue;

        const authClaims = payload['https://api.openai.com/auth'];
        if (authClaims && typeof authClaims === 'object') {
            for (const key of ['chatgpt_account_id', 'account_id', 'user_id', 'chatgpt_user_id']) {
                if (authClaims[key]) return String(authClaims[key]);
            }
        }

        for (const key of ['sub', 'user_id']) {
            if (payload[key]) return String(payload[key]);
        }
    }

    return null;
}

function sameAccount(left, right) {
    const leftAuth = extractStoredAuth(left);
    const rightAuth = extractStoredAuth(right);

    if (!Object.keys(leftAuth).length || !Object.keys(rightAuth).length) {
        return false;
    }

    const leftId = extractAccountId(leftAuth);
    const rightId = extractAccountId(rightAuth);
    if (leftId && rightId) {
        return leftId === rightId;
    }

    const leftTokens = leftAuth.tokens || {};
    const rightTokens = rightAuth.tokens || {};
    for (const key of ['refresh_token', 'id_token', 'access_token']) {
        if (leftTokens[key] && rightTokens[key]) {
            return leftTokens[key] === rightTokens[key];
        }
    }

    const leftEmail = extractEmailFromToken(leftAuth);
    const rightEmail = extractEmailFromToken(rightAuth);
    if (leftEmail && rightEmail) {
        return leftEmail === rightEmail;
    }

    return false;
}

function validateAuthConfig(config) {
    if (!config || typeof config !== 'object') {
        throw new Error('账号配置格式无效');
    }

    const authMode = config.auth_mode;
    const tokens = config.tokens;
    const apiKey = config.OPENAI_API_KEY;

    if (authMode === 'api_key') {
        if (!apiKey) {
            throw new Error('API Key 账号缺少 OPENAI_API_KEY');
        }
        return;
    }

    if (tokens && typeof tokens === 'object') {
        if (tokens.refresh_token || tokens.access_token || tokens.id_token) {
            return;
        }
    }

    if (apiKey) {
        return;
    }

    throw new Error('账号配置缺少可用的认证字段');
}

function buildStoredAccountRecord(authConfig, accountName) {
    const authSnapshot = extractStoredAuth(authConfig);
    validateAuthConfig(authSnapshot);

    const metadata = {
        schema_version: 2,
        account_name: accountName,
        saved_at: new Date().toISOString(),
        email: extractEmailFromToken(authSnapshot),
        account_id: extractAccountId(authSnapshot),
        plan: extractPlanType(authSnapshot),
        auth_mode: authSnapshot.auth_mode || null,
        auth_snapshot: cloneJson(authSnapshot)
    };

    return {
        ...cloneJson(authSnapshot),
        account_name: metadata.account_name,
        saved_at: metadata.saved_at,
        email: metadata.email,
        account_id: metadata.account_id,
        plan: metadata.plan,
        auth_mode: metadata.auth_mode,
        [MANAGER_KEY]: metadata
    };
}

// =============================================================================
// 路径管理 (与 Python config_utils.get_config_paths 一致)
// =============================================================================

async function initPaths() {
    const home = await homeDir();
    const appData = await appDataDir();
    
    // 系统 Codex 配置路径
    const systemAuthFile = await join(home, '.codex', 'auth.json');
    
    // 应用配置目录（通用，不依赖用户桌面路径）
    const codexConfigDir = await join(appData, 'codex-config');
    
    PATHS = {
        systemAuthFile,
        codexConfigDir,
        accountsDir: await join(codexConfigDir, 'accounts'),
        usageCacheDir: await join(codexConfigDir, 'usage_cache'),
        settingsFile: await join(codexConfigDir, 'settings.json'),
        logsFile: await join(codexConfigDir, 'error_logs.json')
    };
    
    console.log('初始化路径:', PATHS);
}

// =============================================================================
// 目录初始化
// =============================================================================

async function ensureDirs() {
    try {
        await mkdir(PATHS.codexConfigDir, { recursive: true });
        await mkdir(PATHS.accountsDir, { recursive: true });
        await mkdir(PATHS.usageCacheDir, { recursive: true });
        console.log('✅ 目录创建成功');
    } catch (e) {
        console.log('⚠️ 目录已存在或创建失败:', e);
    }
}

async function readJsonFileNoThrow(path) {
    try {
        const fileExists = await exists(path);
        if (!fileExists) return null;
        const content = await readTextFile(path);
        return JSON.parse(content);
    } catch (_) {
        return null;
    }
}

async function writeJsonFileNoThrow(path, data) {
    try {
        await writeTextFile(path, JSON.stringify(data, null, 2));
        return true;
    } catch (_) {
        return false;
    }
}

function normalizeSettings(rawSettings) {
    const maxLogEntries = Number(rawSettings?.maxLogEntries);
    const legacyProxyValues = rawSettings?.proxy && typeof rawSettings.proxy === 'object'
        ? Object.entries(rawSettings.proxy)
            .filter(([key, value]) => key !== 'proxyUrl' && typeof value === 'string' && value.trim())
            .map(([, value]) => value)
        : [];
    const proxyUrl = normalizeProxyUrl(
        rawSettings?.proxy?.proxyUrl ||
        legacyProxyValues[0] ||
        ''
    );

    return {
        maxLogEntries: Number.isFinite(maxLogEntries)
            ? Math.max(50, Math.min(5000, Math.round(maxLogEntries)))
            : DEFAULT_SETTINGS.maxLogEntries,
        proxy: {
            proxyUrl
        },
        settingsVersion: DEFAULT_SETTINGS.settingsVersion
    };
}

async function loadSettings() {
    const storedSettings = await readJsonFileNoThrow(PATHS.settingsFile);
    appSettings = normalizeSettings(storedSettings || DEFAULT_SETTINGS);
}

async function saveSettings() {
    await writeJsonFileNoThrow(PATHS.settingsFile, appSettings);
}

function trimLogs(logs) {
    const maxEntries = appSettings.maxLogEntries || DEFAULT_SETTINGS.maxLogEntries;
    if (!Array.isArray(logs)) return [];
    return logs.slice(-maxEntries);
}

async function loadAppLogs() {
    const storedLogs = await readJsonFileNoThrow(PATHS.logsFile);
    appLogs = trimLogs(Array.isArray(storedLogs?.logs) ? storedLogs.logs : []);
}

async function persistLogs() {
    const payload = {
        logs: trimLogs(appLogs)
    };
    appLogs = payload.logs;
    await writeJsonFileNoThrow(PATHS.logsFile, payload);
}

function serializeErrorDetails(details) {
    if (details instanceof Error) {
        return {
            name: details.name,
            message: details.message,
            stack: details.stack || null
        };
    }

    if (details === undefined || details === null) {
        return null;
    }

    if (typeof details === 'string') {
        return { message: details };
    }

    try {
        return JSON.parse(JSON.stringify(details));
    } catch (_) {
        return { message: String(details) };
    }
}

function enqueueLogWrite() {
    logWriteQueue = logWriteQueue
        .then(() => persistLogs())
        .catch(() => {});
    return logWriteQueue;
}

function appendLogEntry(level, message, details = null) {
    const entry = {
        id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        timestamp: new Date().toISOString(),
        level,
        message,
        details: serializeErrorDetails(details)
    };

    appLogs.push(entry);
    appLogs = trimLogs(appLogs);
    enqueueLogWrite();
    renderSettingsLogs();
    return entry;
}

function formatLogEntry(entry) {
    const time = entry?.timestamp
        ? new Date(entry.timestamp).toLocaleString('zh-CN')
        : '-';
    const base = `[${time}] [${String(entry?.level || 'info').toUpperCase()}] ${entry?.message || ''}`;
    const details = entry?.details
        ? JSON.stringify(entry.details, null, 2)
        : '';
    return details ? `${base}\n${details}` : base;
}

function renderSettingsLogs() {
    const logContent = document.getElementById('settings-log-content');
    const logEntryCount = document.getElementById('log-entry-count');
    const lastErrorTime = document.getElementById('last-error-time');
    const logFilePath = document.getElementById('log-file-path');
    const maxLogEntries = document.getElementById('max-log-entries');
    const proxyUrl = document.getElementById('proxy-url');

    if (logEntryCount) {
        logEntryCount.textContent = String(appLogs.length);
    }

    const latestError = [...appLogs].reverse().find((entry) => entry.level === 'error');
    if (lastErrorTime) {
        lastErrorTime.textContent = latestError
            ? new Date(latestError.timestamp).toLocaleString('zh-CN')
            : '-';
    }

    if (logFilePath) {
        logFilePath.textContent = PATHS.logsFile || '-';
    }

    if (maxLogEntries) {
        maxLogEntries.value = String(appSettings.maxLogEntries);
    }

    if (proxyUrl) {
        proxyUrl.value = appSettings.proxy?.proxyUrl || '';
    }

    if (logContent) {
        logContent.textContent = appLogs.length
            ? appLogs.map(formatLogEntry).join('\n\n')
            : '暂无日志';
    }
}

function openSettingsModal() {
    const overlay = document.getElementById('settings-overlay');
    if (!overlay) return;
    renderSettingsLogs();
    overlay.style.display = 'flex';
}

function closeSettingsModal() {
    const overlay = document.getElementById('settings-overlay');
    if (!overlay) return;
    overlay.style.display = 'none';
}

function handleSettingsOverlayClick(event) {
    if (event.target?.id === 'settings-overlay') {
        closeSettingsModal();
    }
}

async function saveSettingsModal() {
    const input = document.getElementById('max-log-entries');
    const proxyUrl = document.getElementById('proxy-url');
    const nextValue = Number(input?.value);
    appSettings = normalizeSettings({
        maxLogEntries: nextValue,
        proxy: {
            proxyUrl: proxyUrl?.value || ''
        }
    });
    appLogs = trimLogs(appLogs);
    await saveSettings();
    await persistLogs();
    renderSettingsLogs();
    showMessage('设置已保存', 'success');
}

async function refreshSettingsLogs() {
    await loadAppLogs();
    renderSettingsLogs();
    showMessage('日志已刷新', 'success');
}

async function clearErrorLogs() {
    const confirmed = await confirm('确定要清空本地错误日志吗？此操作不可恢复。', {
        title: '清空日志',
        okLabel: '清空',
        cancelLabel: '取消'
    });

    if (!confirmed) {
        return;
    }

    appLogs = [];
    await persistLogs();
    renderSettingsLogs();
    showMessage('错误日志已清空', 'success');
}

// =============================================================================
// JSON 文件读写 (与 Python json.load/dump 一致)
// =============================================================================

async function readJsonSafe(path) {
    try {
        const fileExists = await exists(path);
        if (!fileExists) return null;
        
        const content = await readTextFile(path);
        return JSON.parse(content);
    } catch (e) {
        console.error(`读取JSON失败 ${path}:`, e);
        appendLogEntry('error', '读取 JSON 文件失败', { path, error: serializeErrorDetails(e) });
        return null;
    }
}

async function writeJsonSafe(path, data) {
    try {
        const content = JSON.stringify(data, null, 2);
        await writeTextFile(path, content);
        return true;
    } catch (e) {
        console.error(`写入JSON失败 ${path}:`, e);
        appendLogEntry('error', '写入 JSON 文件失败', { path, error: serializeErrorDetails(e) });
        throw e;
    }
}

// =============================================================================
// 账号名生成 (与 Python generate_account_name 一致)
// =============================================================================

function generateAccountName(email) {
    if (!email) return `account_${Date.now()}`;
    const username = email.split('@')[0];
    return username.replace(/[^a-zA-Z0-9._-]/g, '_');
}

// =============================================================================
// 账号加载 (与 Python get_accounts_data 一致)
// =============================================================================

async function loadAccounts() {
    try {
        console.log('📂 开始加载账号，目录:', PATHS.accountsDir);
        const entries = await readDir(PATHS.accountsDir);
        console.log('📋 找到', entries.length, '个文件/目录');
        accounts = [];
        
        // 获取当前账号邮箱
        const currentConfig = await readJsonSafe(PATHS.systemAuthFile);
        if (currentConfig) {
            console.log('当前账号邮箱:', extractEmailFromToken(currentConfig));
        } else {
            console.log('未找到系统auth文件');
        }
        
        // 读取所有账号配置
        for (const entry of entries) {
            if (entry.name && entry.name.endsWith('.json')) {
                const filePath = await join(PATHS.accountsDir, entry.name);
                const config = await readJsonSafe(filePath);
                
                if (config) {
                    const accountName = entry.name.replace('.json', '');
                    const email = extractEmailFromToken(config) || '未知';
                    const planType = extractPlanType(config) || '未知';
                    const savedAt = config.saved_at || '未知时间';
                    const isCurrent = sameAccount(currentConfig, config);
                    const accountId = extractAccountId(config);
                    
                    console.log(`账号: ${accountName}, Email: ${email}, AccountId: ${accountId}, 是否当前: ${isCurrent}`);
                    
                    accounts.push({
                        name: accountName,
                        email,
                        account_id: accountId,
                        plan: planType,
                        saved_at: formatDate(savedAt),
                        is_current: isCurrent,
                        path: filePath,
                        config
                    });
                }
            }
        }
        
        // 排序：当前账号在前
        accounts.sort((a, b) => {
            if (a.is_current && !b.is_current) return -1;
            if (!a.is_current && b.is_current) return 1;
            return a.name.localeCompare(b.name);
        });
        
        console.log(`✅ 加载了 ${accounts.length} 个账号:`, accounts.map(a => `${a.name}(当前:${a.is_current})`).join(', '));
        renderAccounts();
    } catch (e) {
        console.error('加载账号失败:', e);
        showMessage('加载账号列表失败: ' + e, 'error');
    }
}

// =============================================================================
// 提取套餐类型
// =============================================================================

function extractPlanType(config) {
    try {
        if (!config || typeof config !== 'object') return null;

        const manager = config[MANAGER_KEY];
        if (manager?.plan) return manager.plan;
        if (config.plan) return config.plan;

        const authConfig = extractStoredAuth(config);
        if (!authConfig.tokens || !authConfig.tokens.access_token) return null;
        
        const payload = parseJwtPayload(authConfig.tokens.access_token);
        if (payload && payload['https://api.openai.com/auth']) {
            return payload['https://api.openai.com/auth'].chatgpt_plan_type;
        }
    } catch (e) {
        // ignore
    }
    return null;
}

// =============================================================================
// 时间格式化
// =============================================================================

function formatDate(dateStr) {
    try {
        if (dateStr === '未知时间') return dateStr;
        const date = new Date(dateStr);
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${month}-${day} ${hours}:${minutes}`;
    } catch (e) {
        return dateStr;
    }
}

// =============================================================================
// UI 渲染
// =============================================================================

function renderAccounts() {
    const tbody = document.getElementById('accounts-list');
    const emptyState = document.getElementById('empty-state');
    const accountCountEl = document.getElementById('account-count');
    
    // 更新账号计数
    accountCountEl.textContent = `共 ${accounts.length} 个账号`;
    
    if (accounts.length === 0) {
        tbody.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }
    
    tbody.style.display = '';
    emptyState.style.display = 'none';
    
    console.log('🎨 开始渲染', accounts.length, '个账号');
    
    tbody.innerHTML = accounts.map(account => {
        console.log(`渲染账号 ${account.name}: is_current=${account.is_current}`);
        const rowClass = account.is_current ? 'current-row' : '';
        return `
        <tr class="${rowClass}" data-account="${account.name}" onclick="selectRow('${account.name}')">
            <td>
                ${account.is_current ? '<span class="status-indicator current"></span>' : ''}
            </td>
            <td class="account-name-cell">${account.name}</td>
            <td class="account-email-cell">${account.email}</td>
            <td class="account-plan-cell">
                <span class="plan-badge ${getPlanClass(account.plan)}">${account.plan}</span>
            </td>
            <td class="usage-cell" id="usage-primary-${account.name}">
                <span class="usage-text">-</span>
            </td>
            <td class="usage-cell" id="usage-secondary-${account.name}">
                <span class="usage-text">-</span>
            </td>
            <td class="time-cell">${account.saved_at}</td>
            <td>
                <div class="actions-cell">
                    <button class="btn-secondary" onclick="handleSwitchClick(event, '${account.name}')" title="切换到此账号">
                        切换
                    </button>
                    <button class="btn-primary" ${account.is_current ? '' : 'disabled'} onclick="handleRefreshClick(event, '${account.name}')" title="${account.is_current ? '刷新用量数据' : '仅当前账号可刷新'}">
                        刷新
                    </button>
                    <button class="btn-danger" onclick="handleDeleteClick(event, '${account.name}')" title="${account.is_current ? '当前账号请先切换后再删除' : '删除此账号'}">
                        删除
                    </button>
                </div>
            </td>
        </tr>
        `;
    }).join('');
    
    // 延迟加载用量信息
    accounts.forEach((account, index) => {
        setTimeout(() => loadAccountUsage(account.name), index * 100);
    });
}

function getPlanClass(plan) {
    if (!plan || plan === '未知') return '';
    const planLower = plan.toLowerCase();
    if (planLower.includes('plus')) return 'plus';
    if (planLower.includes('pro')) return 'pro';
    return '';
}

function selectRow(accountName) {
    document.querySelectorAll('.accounts-table tbody tr').forEach(row => {
        row.classList.remove('selected-row');
    });
    
    const row = document.querySelector(`tr[data-account="${accountName}"]`);
    if (row) {
        row.classList.add('selected-row');
        selectedAccount = accountName;
    }
}

// 按钮点击处理函数 - 确保事件正确阻止
function handleSwitchClick(event, accountName) {
    event.stopPropagation();
    event.preventDefault();
    quickSwitchAccount(accountName);
}

function handleDeleteClick(event, accountName) {
    event.stopPropagation();
    event.preventDefault();
    quickDeleteAccount(accountName);
}

function handleRefreshClick(event, accountName) {
    event.stopPropagation();
    event.preventDefault();
    refreshCurrentAccountUsage(accountName);
}


// =============================================================================
// 账号操作 (与 Python 逻辑一致)
// =============================================================================

// 快速保存当前账号
async function quickSave() {
    try {
        setButtonLoading('quick-save-btn', true);
        showMessage('正在导入当前账号...', 'success');
        
        const config = await readJsonSafe(PATHS.systemAuthFile);
        if (!config) {
            throw new Error('未找到当前系统认证文件');
        }
        
        const email = extractEmailFromToken(config);
        if (!email) {
            throw new Error('无法从配置中提取邮箱信息');
        }
        
        const accountName = generateAccountName(email);
        const accountRecord = buildStoredAccountRecord(config, accountName);
        const accountFile = await join(PATHS.accountsDir, `${accountName}.json`);
        await writeJsonSafe(accountFile, accountRecord);
        
        showMessage(`成功保存账号: ${accountName} (${email})`, 'success');
        await loadAccounts();
    } catch (e) {
        showMessage('保存账号失败: ' + e.message, 'error');
    } finally {
        setButtonLoading('quick-save-btn', false);
    }
}

// 快速切换账号
async function quickSwitchAccount(accountName) {
    console.log('🔄 准备切换到账号:', accountName);
    console.log('当前accounts数组:', accounts);
    
    const confirmed = await confirm(`确定要切换到账号 '${accountName}' 吗？`, {
        title: '确认切换',
        type: 'warning',
        okLabel: '确定',
        cancelLabel: '取消'
    });
    
    if (!confirmed) {
        console.log('用户取消切换');
        return;
    }
    
    try {
        showMessage(`正在切换到账号 ${accountName}...`, 'success');
        
        const account = accounts.find(a => a.name === accountName);
        console.log('找到账号对象:', account);
        
        if (!account) {
            throw new Error('账号不存在');
        }
        
        if (!account.config) {
            console.error('账号config为空:', account);
            throw new Error('账号配置为空');
        }
        
        console.log('账号配置:', account.config);
        
        const cleanConfig = extractStoredAuth(account.config);
        validateAuthConfig(cleanConfig);

        const currentSystemConfig = await readJsonSafe(PATHS.systemAuthFile);
        if (currentSystemConfig) {
            await writeJsonSafe(`${PATHS.systemAuthFile}.backup`, currentSystemConfig);
        }
        
        console.log('准备写入系统配置:', PATHS.systemAuthFile);
        await writeJsonSafe(PATHS.systemAuthFile, cleanConfig);
        console.log('✅ 系统配置写入成功');
        
        showMessage(`已切换到账号 ${accountName}，现在可以直接刷新官方用量`, 'success');
        selectedAccount = null;
        await loadAccounts();
    } catch (e) {
        console.error('❌ 切换账号错误:', e);
        showMessage('切换账号失败: ' + (e.message || String(e)), 'error');
    }
}

// 快速删除账号
async function quickDeleteAccount(accountName) {
    const confirmed = await confirm(
        `确定要删除账号 '${accountName}' 吗？\n\n此操作不可恢复！`,
        {
            title: '确认删除',
            type: 'warning',
            okLabel: '删除',
            cancelLabel: '取消'
        }
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        const account = accounts.find(a => a.name === accountName);
        if (!account) return;

        // 防止删除当前账号
        if (account.is_current) {
            showMessage('当前账号不可删除，请先切换到其他账号后再删除', 'error');
            return;
        }

        await remove(account.path);
        
        showMessage(`成功删除账号: ${accountName}`, 'success');
        if (selectedAccount === accountName) {
            selectedAccount = null;
        }
        await loadAccounts();
    } catch (e) {
        showMessage('删除账号失败: ' + e.message, 'error');
    }
}


// =============================================================================
// 用量查询功能 (完整实现)
// =============================================================================

// 加载缓存的用量数据
async function loadCachedUsage(email) {
    if (!email) return null;
    
    try {
        const safeEmail = email.replace(/@/g, '_at_').replace(/\./g, '_').replace(/\+/g, '_plus_');
        const cacheFile = await join(PATHS.usageCacheDir, `${safeEmail}_usage.json`);
        const cacheExists = await exists(cacheFile);
        
        if (!cacheExists) return null;
        
        const cacheData = await readJsonSafe(cacheFile);
        if (!cacheData) return null;
        
        // 检查是否过期（30天）
        const lastUpdated = new Date(cacheData.last_updated);
        const now = new Date();
        const daysDiff = (now - lastUpdated) / (1000 * 60 * 60 * 24);
        
        if (daysDiff > 30) return null;
        
        return cacheData.usage_data;
    } catch (e) {
        return null;
    }
}

// 保存用量数据到缓存
async function saveCachedUsage(email, usageData) {
    if (!email || !usageData) return false;
    
    try {
        const safeEmail = email.replace(/@/g, '_at_').replace(/\./g, '_').replace(/\+/g, '_plus_');
        const cacheFile = await join(PATHS.usageCacheDir, `${safeEmail}_usage.json`);
        
        const cacheData = {
            email,
            last_updated: new Date().toISOString(),
            usage_data: usageData
        };
        
        await writeJsonSafe(cacheFile, cacheData);
        return true;
    } catch (e) {
        console.error('保存缓存失败:', e);
        return false;
    }
}

function normalizeWindow(windowData) {
    if (!windowData || typeof windowData !== 'object') return null;

    const usedPercent = Number(windowData.used_percent);
    const limitWindowSeconds = Number(windowData.limit_window_seconds);
    const resetsAt = Number(windowData.reset_at);
    const resetsInSeconds = Number(windowData.reset_after_seconds);

    return {
        used_percent: Number.isFinite(usedPercent) ? usedPercent : null,
        window_minutes: Number.isFinite(limitWindowSeconds) ? limitWindowSeconds / 60 : null,
        limit_window_seconds: Number.isFinite(limitWindowSeconds) ? limitWindowSeconds : null,
        resets_at: Number.isFinite(resetsAt) ? resetsAt : null,
        resets_in_seconds: Number.isFinite(resetsInSeconds) ? resetsInSeconds : null
    };
}

function normalizeRateLimit(rateLimit) {
    if (!rateLimit || typeof rateLimit !== 'object') return {};

    const normalized = {
        allowed: rateLimit.allowed,
        limit_reached: rateLimit.limit_reached
    };

    const primary = normalizeWindow(rateLimit.primary_window);
    const secondary = normalizeWindow(rateLimit.secondary_window);
    if (primary) normalized.primary = primary;
    if (secondary) normalized.secondary = secondary;
    return normalized;
}

function normalizeAdditionalRateLimits(additionalRateLimits) {
    if (!Array.isArray(additionalRateLimits)) return [];

    return additionalRateLimits
        .map((item) => {
            if (!item || typeof item !== 'object') return null;
            const rateLimit = normalizeRateLimit(item.rate_limit);
            if (!Object.keys(rateLimit).length) return null;

            return {
                limit_name: item.limit_name || null,
                metered_feature: item.metered_feature || null,
                allowed: rateLimit.allowed,
                limit_reached: rateLimit.limit_reached,
                primary: rateLimit.primary || null,
                secondary: rateLimit.secondary || null
            };
        })
        .filter(Boolean);
}

async function readSystemAuthConfig() {
    const authExists = await exists(PATHS.systemAuthFile);
    if (!authExists) return null;
    return readJsonSafe(PATHS.systemAuthFile);
}

async function fetchWhamUsage(accessToken) {
    if (!accessToken) {
        throw new Error('当前账号缺少 access_token');
    }

    return invoke('fetch_wham_usage', {
        accessToken,
        proxyConfig: getActiveProxyConfig()
    });
}

// 获取用量摘要
async function getUsageSummary(email, authConfig = null) {
    const summary = {
        check_time: new Date().toLocaleString('zh-CN'),
        status: 'checking',
        email: email || null,
        plan_type: null,
        token_usage: {},
        rate_limits: {},
        additional_rate_limits: [],
        errors: []
    };

    const activeAuth = authConfig || await readSystemAuthConfig();
    if (!activeAuth) {
        summary.errors.push('未找到当前 Codex 认证配置');
        summary.status = 'failed';
        return summary;
    }

    const accessToken = extractAccessToken(activeAuth);
    if (!accessToken) {
        summary.errors.push('当前账号缺少 access_token');
        summary.status = 'failed';
        return summary;
    }

    const resolvedEmail = email || extractEmailFromToken(activeAuth);
    if (resolvedEmail) {
        summary.email = resolvedEmail;
    }

    try {
        const payload = await fetchWhamUsage(accessToken);
        summary.status = 'success';
        summary.email = summary.email || payload?.email || null;
        summary.plan_type = payload?.plan_type || null;
        summary.rate_limits = normalizeRateLimit(payload?.rate_limit);
        summary.additional_rate_limits = normalizeAdditionalRateLimits(payload?.additional_rate_limits);
        summary.raw_usage = payload;
    } catch (error) {
        const errorMessage = error?.message || String(error);
        summary.errors.push(errorMessage);
        summary.status = 'failed';
        appendLogEntry('error', '获取官方用量接口失败', {
            email: summary.email,
            error: errorMessage
        });
        return summary;
    }

    if (summary.email && summary.status === 'success') {
        await saveCachedUsage(summary.email, {
            check_time: summary.check_time,
            status: summary.status,
            plan_type: summary.plan_type,
            token_usage: summary.token_usage,
            rate_limits: summary.rate_limits,
            additional_rate_limits: summary.additional_rate_limits,
            raw_usage: summary.raw_usage,
            errors: summary.errors
        });
    }

    return summary;
}

function getResetDate(limit) {
    if (!limit || typeof limit !== 'object') return null;

    if (typeof limit.resets_at === 'number') {
        return new Date(limit.resets_at * 1000);
    }

    if (typeof limit.resets_in_seconds === 'number') {
        return new Date(Date.now() + limit.resets_in_seconds * 1000);
    }

    return null;
}

function formatResetInfo(limit, includeDate = false) {
    const resetDate = getResetDate(limit);
    if (!resetDate || Number.isNaN(resetDate.getTime())) return '';

    if (includeDate) {
        return `${resetDate.toLocaleDateString('zh-CN', {month: '2-digit', day: '2-digit'})} ${resetDate.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}`;
    }

    return resetDate.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
}

function getRemainingPercent(limit) {
    const usedPercent = Number(limit?.used_percent);
    if (!Number.isFinite(usedPercent)) return null;

    const remainingPercent = 100 - usedPercent;
    return Math.max(0, Math.min(100, Math.round(remainingPercent)));
}

// 格式化用量单元格 HTML
function formatUsageCell(percent, resetInfo, fromCache = false) {
    if (percent === null || percent === undefined) {
        return '<span class="usage-text" style="color: var(--text-muted);">-</span>';
    }
    
    const barClass = percent < 20 ? 'high' : percent < 40 ? 'medium' : 'low';
    const cacheIndicator = fromCache ? ' <span class="cache-badge" title="缓存数据">缓存</span>' : '';
    
    return `
        <div class="usage-indicator">
            <div class="usage-bar-mini">
                <div class="usage-bar-fill ${barClass}" style="width: ${percent}%;"></div>
            </div>
            <span class="usage-text">${percent}%${cacheIndicator}</span>
        </div>
        ${resetInfo ? `<div class="usage-reset">${resetInfo}</div>` : ''}
    `;
}

function getUsageCells(accountName) {
    return {
        primaryCell: document.getElementById(`usage-primary-${accountName}`),
        secondaryCell: document.getElementById(`usage-secondary-${accountName}`)
    };
}

function renderEmptyUsageCell(cell, text = '-', colorVar = '--text-muted') {
    if (!cell) return;
    cell.innerHTML = `<span class="usage-text" style="color: var(${colorVar});">${text}</span>`;
}

function renderUsageLoading(accountName) {
    const { primaryCell, secondaryCell } = getUsageCells(accountName);
    renderEmptyUsageCell(primaryCell, '刷新中...', '--text-muted');
    renderEmptyUsageCell(secondaryCell, '刷新中...', '--text-muted');
}

function renderUsageRateLimits(accountName, rateLimits, fromCache = false) {
    const { primaryCell, secondaryCell } = getUsageCells(accountName);
    if (!primaryCell || !secondaryCell) return false;

    const primary = rateLimits?.primary;
    const secondary = rateLimits?.secondary;

    if (primary) {
        const percent = getRemainingPercent(primary);
        const resetInfo = formatResetInfo(primary, false);
        primaryCell.innerHTML = formatUsageCell(percent, resetInfo, fromCache);
    } else {
        renderEmptyUsageCell(primaryCell);
    }

    if (secondary) {
        const percent = getRemainingPercent(secondary);
        const resetInfo = formatResetInfo(secondary, true);
        secondaryCell.innerHTML = formatUsageCell(percent, resetInfo, fromCache);
    } else {
        renderEmptyUsageCell(secondaryCell);
    }

    return true;
}

// 加载账号用量 (表格版本)
async function loadAccountUsage(accountName, options = {}) {
    const account = accounts.find(a => a.name === accountName);
    if (!account) return;

    const {
        preloadedSummary = null,
        allowCacheFallback = true,
        skipLiveFetch = false
    } = options;

    try {
        if (preloadedSummary?.status === 'success' && preloadedSummary.rate_limits) {
            renderUsageRateLimits(accountName, preloadedSummary.rate_limits, !!preloadedSummary.from_cache);
            return;
        }

        // 当前账号优先走官方接口，避免长期显示旧缓存
        if (account.is_current && !skipLiveFetch) {
            const currentAuth = await readSystemAuthConfig();
            const summary = await getUsageSummary(account.email, currentAuth);
            if (summary.status === 'success' && summary.rate_limits) {
                renderUsageRateLimits(accountName, summary.rate_limits, false);
                return;
            }
        }

        if (allowCacheFallback) {
            const cachedUsage = await loadCachedUsage(account.email);
            if (cachedUsage?.rate_limits) {
                renderUsageRateLimits(accountName, cachedUsage.rate_limits, true);
                return;
            }
        }

        if (account.is_current) {
            const { primaryCell, secondaryCell } = getUsageCells(accountName);
            renderEmptyUsageCell(primaryCell, '无数据', '--warning');
            renderEmptyUsageCell(secondaryCell, '无数据', '--warning');
        } else {
            const { primaryCell, secondaryCell } = getUsageCells(accountName);
            renderEmptyUsageCell(primaryCell);
            renderEmptyUsageCell(secondaryCell);
        }
    } catch (error) {
        const { primaryCell, secondaryCell } = getUsageCells(accountName);
        renderEmptyUsageCell(primaryCell, '错误', '--danger');
        renderEmptyUsageCell(secondaryCell, '错误', '--danger');
    }
}

// 刷新当前账号用量 (与Web端一致)
async function refreshCurrentAccountUsage(accountName) {
    const account = accounts.find(a => a.name === accountName);
    if (!account || !account.is_current) {
        showMessage('只能刷新当前账号的用量', 'error');
        return;
    }

    const { primaryCell, secondaryCell } = getUsageCells(accountName);
    const previousPrimaryHtml = primaryCell?.innerHTML || '';
    const previousSecondaryHtml = secondaryCell?.innerHTML || '';
    
    try {
        showMessage(`正在刷新账号 ${accountName} 的用量数据...`, 'success');
        renderUsageLoading(accountName);

        const currentAuth = await readSystemAuthConfig();
        const summary = await getUsageSummary(account.email, currentAuth);
        
        if (summary.status === 'success') {
            await loadAccountUsage(accountName, {
                preloadedSummary: summary,
                allowCacheFallback: false,
                skipLiveFetch: true
            });
            showMessage(`已刷新账号 ${account.email} 的用量数据`, 'success');
        } else {
            const errorMsg = summary.errors?.[0] || '未知错误';
            if (primaryCell) primaryCell.innerHTML = previousPrimaryHtml;
            if (secondaryCell) secondaryCell.innerHTML = previousSecondaryHtml;
            showMessage(`刷新失败: ${errorMsg}`, 'error');
        }
    } catch (error) {
        if (primaryCell) primaryCell.innerHTML = previousPrimaryHtml;
        if (secondaryCell) secondaryCell.innerHTML = previousSecondaryHtml;
        showMessage('刷新失败: ' + error.message, 'error');
    }
}

// =============================================================================
// UI 辅助函数
// =============================================================================

function showMessage(message, type = 'success') {
    const messageArea = document.getElementById('message-area');
    const icon = type === 'success' ? '[成功]' : '[错误]';
    const alertClass = type === 'success' ? 'alert-success' : 'alert-error';

    if (type === 'error') {
        appendLogEntry('error', String(message));
    }
    
    const toast = document.createElement('div');
    toast.className = `toast ${alertClass}`;
    toast.innerHTML = `${icon} ${message}`;
    
    messageArea.innerHTML = '';
    messageArea.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease-out reverse';
        setTimeout(() => {
            if (messageArea.contains(toast)) {
                messageArea.removeChild(toast);
            }
        }, 300);
    }, 3000);
}

function setButtonLoading(buttonId, loading) {
    const button = document.getElementById(buttonId);
    if (!button) return;
    
    if (loading) {
        button.disabled = true;
        button.dataset.originalText = button.innerHTML;
        const icon = button.querySelector('.btn-icon');
        const text = button.querySelector('span:not(.btn-icon)');
        if (icon && text) {
            icon.textContent = '⏳';
            text.textContent = '处理中';
        }
    } else {
        button.disabled = false;
        button.innerHTML = button.dataset.originalText || button.innerHTML;
    }
}

function refreshData() {
    if (!isLoading) {
        selectedAccount = null;
        loadAccounts();
    }
}

// =============================================================================
// 初始化应用
// =============================================================================

async function initApp() {
    try {
        console.log('🚀 初始化 Tauri 应用...');
        await initPaths();
        await ensureDirs();
        await loadSettings();
        await loadAppLogs();
        renderSettingsLogs();
        await loadAccounts();
        console.log('✅ 应用初始化完成');
    } catch (e) {
        console.error('初始化失败:', e);
        appendLogEntry('error', '应用初始化失败', serializeErrorDetails(e));
        showMessage('应用初始化失败: ' + e.message, 'error');
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initApp);

// 导出全局函数供 HTML 调用
window.quickSave = quickSave;
window.quickSwitchAccount = quickSwitchAccount;
window.quickDeleteAccount = quickDeleteAccount;
window.selectRow = selectRow;
window.refreshCurrentAccountUsage = refreshCurrentAccountUsage;
window.refreshData = refreshData;
window.handleSwitchClick = handleSwitchClick;
window.handleDeleteClick = handleDeleteClick;
window.handleRefreshClick = handleRefreshClick;
window.openSettingsModal = openSettingsModal;
window.closeSettingsModal = closeSettingsModal;
window.handleSettingsOverlayClick = handleSettingsOverlayClick;
window.saveSettingsModal = saveSettingsModal;
window.refreshSettingsLogs = refreshSettingsLogs;
window.clearErrorLogs = clearErrorLogs;

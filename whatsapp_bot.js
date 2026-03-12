/**
 * whatsapp_bot.js — Auto-reply to WhatsApp messages using Qwen CLI
 * Replaces whatsapp_watcher.py (Playwright approach was unreliable)
 *
 * First run: scan the QR code shown in terminal with your phone.
 * Session is saved to ./whatsapp_bot_session/ — no QR needed after that.
 *
 * Usage:  node whatsapp_bot.js
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const { execSync, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const VAULT_DIR = __dirname;
const SESSION_DIR = path.join(VAULT_DIR, 'whatsapp_bot_session');

// ── Client setup ─────────────────────────────────────────────────────────────

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
        ],
    },
});

// ── QR code (only needed on first run or if session expires) ─────────────────

client.on('qr', (qr) => {
    console.log('\n[whatsapp_bot] Scan this QR code with your phone:\n');
    qrcode.generate(qr, { small: true });
});

client.on('authenticated', () => {
    console.log('[whatsapp_bot] Authenticated ✓');
});

client.on('ready', () => {
    console.log('[whatsapp_bot] WhatsApp ready. Auto-replying to all messages.');
});

client.on('auth_failure', (msg) => {
    console.error('[whatsapp_bot] Auth failed:', msg);
    console.error('[whatsapp_bot] Delete ./whatsapp_bot_session/ and restart to re-scan QR.');
});

client.on('disconnected', (reason) => {
    console.error('[whatsapp_bot] Disconnected:', reason);
    process.exit(1); // PM2 will auto-restart
});

// ── Message handler ───────────────────────────────────────────────────────────

const seen = new Set();

client.on('message', async (msg) => {
    try {
        // Skip: outgoing, status updates, group messages (optional), already seen
        if (msg.fromMe) return;
        if (msg.type === 'e2e_notification' || msg.type === 'notification_template') return;

        const dedup = `${msg.from}|${msg.body.slice(0, 80)}`;
        if (seen.has(dedup)) return;
        seen.add(dedup);

        const sender = msg._data.notifyName || msg.from;
        const body   = msg.body;

        console.log(`[whatsapp_bot] Message from ${sender}: ${body.slice(0, 80)}`);

        // Get Qwen reply
        const prompt = `You are an AI assistant replying to a WhatsApp message on behalf of your employer.\nSender: ${sender}\nMessage: ${body}\n\nWrite a short, friendly, professional reply in 1-3 sentences.\nSign off as: AI Assistant\nOutput ONLY the reply text.`;

        const result = spawnSync(
            'qwen',
            [prompt, '--output-format', 'text', '--approval-mode', 'yolo'],
            { encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'pipe'] }
        );

        const reply = (result.stdout || '').trim();

        if (!reply || result.status !== 0) {
            console.error(`[whatsapp_bot] Qwen failed. RC=${result.status} ERR=${(result.stderr||'').slice(0,100)}`);
            return;
        }

        await msg.reply(reply);
        console.log(`[whatsapp_bot] Auto-replied to ${sender} ✓`);

    } catch (err) {
        console.error('[whatsapp_bot] Error:', err.message);
    }
});

// ── Start ─────────────────────────────────────────────────────────────────────

console.log('[whatsapp_bot] Starting...');
client.initialize();

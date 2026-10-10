const chatForm = document.getElementById("chat-form");
let conversationId = document.body.dataset.conversationId || "";
const searchToggle = document.getElementById("search-web");
let searchWeb = false;
const codingToggle = document.getElementById("coding-mode");
let codingMode = false;
const documentList = document.getElementById("document-list");
const documentStatus = document.getElementById("document-status");
const attachmentButton = document.getElementById("attachment-button");
const attachmentInput = document.getElementById("attachment-file");
const attachmentChips = document.getElementById("attachment-chips");
const modelSelect = document.getElementById("chat-model");
const thinkingToggle = document.getElementById("thinking-enabled");
const contextSelect = document.getElementById("context-size");
let selectedDocumentIds = new Set([...documentList.querySelectorAll('input:checked')].map(input => input.value));
let knownDocuments = [];
function updateGroundingMode() {
    searchToggle.setAttribute("aria-pressed", String(searchWeb));
    searchToggle.textContent = `Search web · ${searchWeb ? "On" : "Off"}`;
    document.getElementById("search-note").textContent = searchWeb
        ? "Web Search is active for the next question; attached files remain saved to this chat"
        : selectedDocumentIds.size
            ? "Attached files are searched locally when relevant"
            : "Qwen runs locally · Attach a file or enable Web Search when needed";
}
function updateCodingMode() {
    codingToggle.setAttribute("aria-pressed", String(codingMode));
    codingToggle.textContent = `</> Coding · ${codingMode ? "On" : "Off"}`;
}
codingToggle.addEventListener("click", () => {
    codingMode = !codingMode;
    updateCodingMode();
});
searchToggle.addEventListener("click", () => {
    searchWeb = !searchWeb;
    updateGroundingMode();
});
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send-button");
const stopButton = document.getElementById("stop-button");
const chatArea = document.getElementById("chat-area");
const notice = document.getElementById("notice");
const sidebar = document.getElementById("sidebar");
const menuButton = document.getElementById("menu-button");
const sidebarClose = document.getElementById("sidebar-close");
const sidebarScrim = document.getElementById("sidebar-scrim");
const fontButtons = document.querySelectorAll("[data-font-size]");

let activeController = null;
let failedUserMessage = null;
if (document.body.dataset.pendingMessage === "true") {
    const article = document.querySelector("#conversation .message.user:last-child");
    if (article) failedUserMessage = { article, message: messageInput.value };
}
let renderFrame = null;
const jumpLatestButton = document.getElementById("jump-latest");
const promptNavigation = document.getElementById("prompt-navigation");
const promptNavigationTrack = document.getElementById("prompt-navigation-track");
const BOTTOM_THRESHOLD = 180;
let unseenLatest = false;
let promptObserver = null;


function appendInlineFormatting(container, text) {
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g;
    let position = 0;

    for (const match of text.matchAll(pattern)) {
        container.append(document.createTextNode(text.slice(position, match.index)));
        const token = match[0];
        let element;

        if (token.startsWith("`")) {
            element = document.createElement("code");
            element.textContent = token.slice(1, -1);
        } else if (token.startsWith("**") || token.startsWith("__")) {
            element = document.createElement("strong");
            element.textContent = token.slice(2, -2);
        } else {
            element = document.createElement("em");
            element.textContent = token.slice(1, -1);
        }

        container.append(element);
        position = match.index + token.length;
    }

    container.append(document.createTextNode(text.slice(position)));
}


function tableCells(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
}


function isTableDivider(line) {
    const cells = tableCells(line);
    return cells.length > 1 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}


function makeCodeBlock(codeText, language) {
    const wrapper = document.createElement("div");
    wrapper.className = "code-block";

    const toolbar = document.createElement("div");
    toolbar.className = "code-toolbar";

    const label = document.createElement("span");
    label.textContent = language || "code";

    const copyButton = document.createElement("button");
    copyButton.className = "copy-code";
    copyButton.type = "button";
    copyButton.textContent = "Copy code";
    copyButton.addEventListener("click", async () => {
        try {
            await copyText(codeText);
            showCopiedFeedback(copyButton, "Copy code");
        } catch {
            showTemporaryLabel(copyButton, "Copy failed", "Copy code");
        }
    });

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = codeText;
    pre.append(code);
    toolbar.append(label, copyButton);
    wrapper.append(toolbar, pre);
    return wrapper;
}


function renderMarkdown(container, markdown) {
    container.replaceChildren();
    container.dataset.markdown = markdown;

    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    let index = 0;

    while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) {
            index += 1;
            continue;
        }

        const fence = line.match(/^```\s*([\w.+-]*)\s*$/);
        if (fence) {
            const codeLines = [];
            index += 1;
            while (index < lines.length && !/^```\s*$/.test(lines[index])) {
                codeLines.push(lines[index]);
                index += 1;
            }
            if (index < lines.length) index += 1;
            container.append(makeCodeBlock(codeLines.join("\n"), fence[1]));
            continue;
        }

        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            const element = document.createElement(`h${heading[1].length + 2}`);
            appendInlineFormatting(element, heading[2]);
            container.append(element);
            index += 1;
            continue;
        }

        if (index + 1 < lines.length && line.includes("|") && isTableDivider(lines[index + 1])) {
            const tableWrapper = document.createElement("div");
            tableWrapper.className = "table-scroll";
            const table = document.createElement("table");
            const thead = document.createElement("thead");
            const headerRow = document.createElement("tr");
            tableCells(line).forEach(cell => {
                const th = document.createElement("th");
                appendInlineFormatting(th, cell);
                headerRow.append(th);
            });
            thead.append(headerRow);
            table.append(thead);
            index += 2;

            const tbody = document.createElement("tbody");
            while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
                const row = document.createElement("tr");
                tableCells(lines[index]).forEach(cell => {
                    const td = document.createElement("td");
                    appendInlineFormatting(td, cell);
                    row.append(td);
                });
                tbody.append(row);
                index += 1;
            }
            table.append(tbody);
            tableWrapper.append(table);
            container.append(tableWrapper);
            continue;
        }

        const unordered = line.match(/^\s*[-*]\s+(.+)$/);
        const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
        if (unordered || ordered) {
            const list = document.createElement(unordered ? "ul" : "ol");
            const itemPattern = unordered ? /^\s*[-*]\s+(.+)$/ : /^\s*\d+[.)]\s+(.+)$/;
            while (index < lines.length) {
                const item = lines[index].match(itemPattern);
                if (!item) break;
                const li = document.createElement("li");
                appendInlineFormatting(li, item[1]);
                list.append(li);
                index += 1;
            }
            container.append(list);
            continue;
        }

        if (/^>\s?/.test(line)) {
            const quote = document.createElement("blockquote");
            const quoteLines = [];
            while (index < lines.length && /^>\s?/.test(lines[index])) {
                quoteLines.push(lines[index].replace(/^>\s?/, ""));
                index += 1;
            }
            appendInlineFormatting(quote, quoteLines.join(" "));
            container.append(quote);
            continue;
        }

        if (/^\s*([-*_])\1\1+\s*$/.test(line)) {
            container.append(document.createElement("hr"));
            index += 1;
            continue;
        }

        const paragraphLines = [line.trim()];
        index += 1;
        while (index < lines.length && lines[index].trim()) {
            const next = lines[index];
            const startsBlock = /^```|^#{1,4}\s|^\s*[-*]\s+|^\s*\d+[.)]\s+|^>\s?/.test(next);
            const startsTable = index + 1 < lines.length && next.includes("|") && isTableDivider(lines[index + 1]);
            if (startsBlock || startsTable) break;
            paragraphLines.push(next.trim());
            index += 1;
        }
        const paragraph = document.createElement("p");
        appendInlineFormatting(paragraph, paragraphLines.join(" "));
        container.append(paragraph);
    }
}


function scheduleMarkdownRender(container, markdown, afterRender = null) {
    if (renderFrame) cancelAnimationFrame(renderFrame);
    renderFrame = requestAnimationFrame(() => {
        renderMarkdown(container, markdown);
        renderFrame = null;
        afterRender?.();
    });
}


function createMessage(role, content = "") {
    const article = document.createElement("article");
    article.className = `message ${role}`;
    article.dataset.role = role;

    const rail = document.createElement("div");
    rail.className = "message-rail";
    rail.setAttribute("aria-hidden", "true");
    const avatar = document.createElement("span");
    avatar.textContent = role === "user" ? "Y" : "✦";
    rail.append(avatar);

    const body = document.createElement("div");
    body.className = "message-body";
    const heading = document.createElement("div");
    heading.className = "message-heading";
    const title = document.createElement("h2");
    title.textContent = role === "user" ? "You" : "Study Assistant";
    heading.append(title);

    if (role === "assistant") {
        const label = document.createElement("span");
        label.className = "answer-label";
        const dot = document.createElement("i");
        dot.setAttribute("aria-hidden", "true");
        label.append(dot, ` ${modelSelect.options[modelSelect.selectedIndex]?.text || "LOCAL MODEL"} · LOCAL`);
        heading.append(label);
    }

    updateFooterModel(modelSelect.options[modelSelect.selectedIndex]?.text || "LOCAL MODEL");

    const messageContent = document.createElement("div");
    messageContent.className = role === "assistant" ? "message-content markdown-content" : "message-content";
    if (role === "assistant") renderMarkdown(messageContent, content);
    else messageContent.textContent = content;

    body.append(heading, messageContent);
    if (role === "assistant") body.append(createMessageActions());
    article.append(rail, body);
    return { article, messageContent };
}


function createMessageActions() {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const copy = document.createElement("button");
    copy.className = "text-action copy-answer";
    copy.type = "button";
    copy.setAttribute("aria-label", "Copy this answer");
    copy.innerHTML = '<span aria-hidden="true">▢</span> Copy';
    actions.append(copy);
    return actions;
}


function addRegenerateButton(article) {
    document.querySelectorAll(".regenerate").forEach(button => button.remove());
    const actions = article.querySelector(".message-actions");
    if (!actions) return;
    const button = document.createElement("button");
    button.className = "text-action regenerate";
    button.type = "button";
    button.innerHTML = '<span aria-hidden="true">↻</span> Regenerate';
    actions.append(button);
}


function renderRuntimeMeta(article, runtime) {
    article.querySelector(".response-meta")?.remove();
    if (!runtime) return;
    const details = document.createElement("details");
    details.className = "response-meta";
    const summary = document.createElement("summary");
    const selected = [...modelSelect.options].find(option => option.value === runtime.model);
    const modelName = selected?.textContent || runtime.model || "Local model";
    const parts = [modelName];
    if (runtime.tokens_per_second) parts.push(`${runtime.tokens_per_second} tok/s`);
    if (runtime.total_duration) parts.push(`${(runtime.total_duration / 1e9).toFixed(1)} s`);
    summary.textContent = parts.join(" · ");
    const metrics = document.createElement("div");
    if (runtime.prompt_eval_count != null) {
        const prompt = document.createElement("span");
        prompt.textContent = `Prompt: ${runtime.prompt_eval_count} tokens`;
        metrics.append(prompt);
    }
    if (runtime.eval_count != null) {
        const answer = document.createElement("span");
        answer.textContent = `Answer: ${runtime.eval_count} tokens`;
        metrics.append(answer);
    }
    details.append(summary, metrics);
    article.querySelector(".answer-sources, .message-actions").before(details);
    const label = article.querySelector(".answer-label");
    if (label) label.lastChild.textContent = ` ${modelName.toUpperCase()} · LOCAL`;
}


function getOrCreateConversation() {
    let conversation = document.getElementById("conversation");
    if (conversation) return conversation;

    chatArea.replaceChildren();
    conversation = document.createElement("section");
    conversation.id = "conversation";
    conversation.className = "conversation";
    conversation.setAttribute("aria-label", "Conversation");
    conversation.innerHTML = `
        <div class="conversation-heading">
            <div><p class="edition-label"><span>✦</span> ACTIVE STUDY THREAD</p><h1 id="conversation-title">New study conversation</h1></div>
            <span id="exchange-count">0 exchanges</span>
        </div>`;
    chatArea.append(conversation);
    return conversation;
}


function updateExchangeCount() {
    const count = document.querySelectorAll(".message.user").length;
    const element = document.getElementById("exchange-count");
    if (element) element.textContent = `${count} ${count === 1 ? "exchange" : "exchanges"}`;
}


function promptPreview(article) {
    const text = article.querySelector(".message-content")?.textContent.trim().replace(/\s+/g, " ") || "Prompt";
    return text.length > 72 ? `${text.slice(0, 69)}…` : text;
}


function setActivePrompt(article) {
    promptNavigationTrack.querySelectorAll(".prompt-marker").forEach(marker => {
        const active = marker.dataset.promptTarget === article?.id;
        marker.classList.toggle("active", active);
        marker.setAttribute("aria-current", active ? "true" : "false");
    });
}


function updateVisiblePrompt() {
    const prompts = [...document.querySelectorAll("#conversation .message.user")];
    if (!prompts.length) return;
    const focusLine = window.innerHeight * .32;
    let current = prompts[0];
    for (const prompt of prompts) {
        if (prompt.getBoundingClientRect().top <= focusLine) current = prompt;
        else break;
    }
    setActivePrompt(current);
}


function rebuildPromptNavigation() {
    promptObserver?.disconnect();
    promptNavigationTrack.replaceChildren();
    const prompts = [...document.querySelectorAll("#conversation .message.user")];
    promptNavigation.classList.toggle("is-hidden", prompts.length === 0);
    if (!prompts.length) return;

    prompts.forEach((prompt, index) => {
        prompt.id = `prompt-${index + 1}`;
        const marker = document.createElement("button");
        marker.type = "button";
        marker.className = "prompt-marker";
        marker.dataset.promptTarget = prompt.id;
        marker.dataset.preview = promptPreview(prompt);
        marker.setAttribute("aria-label", `Go to prompt ${index + 1}: ${marker.dataset.preview}`);
        marker.addEventListener("click", () => {
            setActivePrompt(prompt);
            prompt.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        promptNavigationTrack.append(marker);
    });

    promptObserver = new IntersectionObserver(updateVisiblePrompt, {
        root: null,
        rootMargin: "-12% 0px -72% 0px",
        threshold: 0,
    });
    prompts.forEach(prompt => promptObserver.observe(prompt));
    updateVisiblePrompt();
}


function updateConversationTitle(title) {
    const activeTitle = document.querySelector('.history-row .nav-item[aria-current="page"] strong');
    if (activeTitle) activeTitle.textContent = title;
    ["conversation-title", "sidebar-title", "topbar-title"].forEach(id => {
        const element = document.getElementById(id);
        if (element) element.textContent = title;
    });
    document.title = `${title} · AI Study Assistant`;
}


function ensureDownloadLink() {
    document.querySelector(".download-link")?.classList.remove("is-hidden");
}


function isNearPageBottom() {
    return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - BOTTOM_THRESHOLD;
}


function updateJumpLatest() {
    jumpLatestButton.classList.toggle("is-hidden", !unseenLatest);
}


function markNewContent() {
    unseenLatest = !isNearPageBottom();
    updateJumpLatest();
}


function jumpToLatest(smooth = true) {
    unseenLatest = false;
    updateJumpLatest();
    if (smooth) window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
    else window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
}


function setGenerating(isGenerating) {
    documentList.querySelectorAll('input, button').forEach(input => {
        input.disabled = isGenerating || (input.type === 'checkbox' && input.dataset.notReady === 'true');
    });
    attachmentButton.disabled = isGenerating;
    attachmentInput.disabled = isGenerating;
    attachmentChips.querySelectorAll('button').forEach(button => button.disabled = isGenerating);
    modelSelect.disabled = isGenerating;
    thinkingToggle.disabled = isGenerating;
    contextSelect.disabled = isGenerating;
    searchToggle.disabled = isGenerating;
    codingToggle.disabled = isGenerating;
    messageInput.disabled = isGenerating;
    sendButton.disabled = isGenerating;
    sendButton.classList.toggle("is-hidden", isGenerating);
    stopButton.classList.toggle("is-hidden", !isGenerating);
    document.querySelectorAll(".regenerate").forEach(button => button.disabled = isGenerating);
    chatForm.classList.toggle("is-generating", isGenerating);
}


function showNotice(message, kind = "info") {
    notice.textContent = message;
    notice.className = `notice ${kind}`;
}


function clearNotice() {
    notice.textContent = "";
    notice.className = "notice is-hidden";
}


function showThinking(container) {
    const thinking = document.createElement("div");
    thinking.className = "thinking";
    thinking.innerHTML = '<span></span><span></span><span></span><em>Thinking locally</em>';
    container.replaceChildren(thinking);
}


async function copyText(text) {
    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch {
            // Fall back to the browser's older copy command when permission is unavailable.
        }
    }
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.append(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
}


function showCopiedFeedback(button) {
    const originalLabel = button.innerHTML;
    button.textContent = "Copied";
    button.classList.add("copied");
    setTimeout(() => {
        button.innerHTML = originalLabel;
        button.classList.remove("copied");
    }, 1400);
}


function showTemporaryLabel(button, label) {
    const originalLabel = button.innerHTML;
    button.textContent = label;
    setTimeout(() => button.innerHTML = originalLabel, 1400);
}


function setSidebarOpen(isOpen) {
    document.body.classList.toggle("sidebar-open", isOpen);
    menuButton?.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) sidebarClose?.focus();
    else if (document.activeElement === sidebarClose) menuButton?.focus();
}


function applyFontSize(size, savePreference = true) {
    const allowedSizes = ["standard", "large", "extra-large"];
    const selectedSize = allowedSizes.includes(size) ? size : "standard";
    document.documentElement.dataset.fontSize = selectedSize;
    fontButtons.forEach(button => {
        button.setAttribute("aria-pressed", String(button.dataset.fontSize === selectedSize));
    });
    if (savePreference) {
        try {
            localStorage.setItem("study-font-size", selectedSize);
        } catch {
            // The setting still applies for this page when storage is unavailable.
        }
    }
}


async function readEventStream(response, onEvent) {
    if (!response.ok || !response.body) throw new Error("The response stream could not start.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
            if (line.trim()) onEvent(JSON.parse(line));
        }
        if (done) break;
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
}


async function runGeneration({ url, assistantArticle, assistantContent, userMessage = "", userArticle = null, originalMarkdown = "" }) {
    clearNotice();
    activeController = new AbortController();
    setGenerating(true);
    showThinking(assistantContent);
    assistantArticle.classList.add("generating");
    let markdown = "";
    let completed = false;
    let streamError = null;
    unseenLatest = false;
    updateJumpLatest();

    try {
        const body = new FormData();
        body.append("conversation_id", conversationId);
        if (url === "/chat") {
            body.append("message", userMessage);
            body.append("search_web", String(searchWeb));
            body.append("document_ids", JSON.stringify([...selectedDocumentIds]));
            body.append("chat_model", modelSelect.value);
            body.append("thinking", String(thinkingToggle.checked));
            body.append("num_ctx", contextSelect.value);
            body.append("coding_mode", String(codingMode));
        }
        const response = await fetch(url, { method: "POST", body, signal: activeController.signal });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(typeof error.detail === 'string' ? error.detail : 'The request could not start. Please retry.');
        }

        await readEventStream(response, event => {
            if (event.type === "token") {
                markdown += event.content;
                scheduleMarkdownRender(assistantContent, markdown, markNewContent);
            } else if (event.type === "conversation") {
                selectSavedConversation(event.conversation_id, event.title);
            } else if (event.type === "status") {
                const label = assistantContent.querySelector(".thinking em");
                if (label) label.textContent = event.message;
            } else if (event.type === "sources") {
                renderSources(assistantArticle, event.sources);
                requestAnimationFrame(markNewContent);
            } else if (event.type === "patch") {
                renderPatchCard(event.patch, assistantArticle);
            } else if (event.type === "error") {
                streamError = event.message;
            } else if (event.type === "done") {
                if (typeof event.content === "string") markdown = event.content;
                renderRuntimeMeta(assistantArticle, event.runtime);
                completed = true;
                updateConversationTitle(event.title);
            }
        });

        if (streamError) throw new Error(streamError);
        if (!completed) throw new Error("The response ended before the model finished.");
        renderMarkdown(assistantContent, markdown);
        requestAnimationFrame(markNewContent);
        assistantArticle.classList.remove("generating", "message-failed");
        addRegenerateButton(assistantArticle);
        ensureDownloadLink();
        failedUserMessage = null;
    } catch (error) {
        const stopped = error.name === "AbortError";
        const message = stopped ? "Generation stopped. Your message was kept so you can try again." : error.message;
        showNotice(message, stopped ? "info" : "error");

        if (url === "/regenerate") {
            renderMarkdown(assistantContent, originalMarkdown);
            addRegenerateButton(assistantArticle);
        } else {
            assistantArticle.remove();
            userArticle?.classList.add("message-failed");
            failedUserMessage = { article: userArticle, message: userMessage };
            messageInput.value = userMessage;
            resizeTextarea();
        }
    } finally {
        if (renderFrame) cancelAnimationFrame(renderFrame);
        renderFrame = null;
        assistantArticle.classList.remove("generating");
        activeController = null;
        setGenerating(false);
        messageInput.focus();
        updateExchangeCount();
        updateJumpLatest();
    }
}


function renderPatchCard(patch, afterArticle = null) {
    const existing = document.querySelector(`[data-patch-id="${patch.id}"]`);
    if (existing) existing.remove();
    const card = document.createElement("section");
    card.className = "patch-card";
    card.dataset.patchId = patch.id;
    card.dataset.patchStatus = patch.status;
    const heading = document.createElement("div");
    heading.className = "patch-heading";
    const label = document.createElement("span"); label.textContent = "Proposed change";
    const status = document.createElement("strong"); status.textContent = patch.status.toUpperCase();
    heading.append(label, status);
    const summary = document.createElement("p"); summary.textContent = patch.summary;
    const diff = document.createElement("pre"); diff.className = "patch-diff"; diff.textContent = patch.diff;
    const info = document.createElement("p"); info.className = "patch-stats";
    info.textContent = `Files: ${patch.patch.files} · Additions: ${patch.patch.additions} · Deletions: ${patch.patch.deletions}`;
    card.append(heading, summary, diff, info);
    if (patch.status === "proposed") {
        const actions = document.createElement("div"); actions.className = "patch-actions";
        const reject = document.createElement("button"); reject.type = "button"; reject.className = "patch-reject"; reject.textContent = "Reject";
        const apply = document.createElement("button"); apply.type = "button"; apply.className = "patch-apply"; apply.textContent = "Apply & Test";
        actions.append(reject, apply); card.append(actions);
    }
    if (afterArticle) afterArticle.after(card);
    else document.getElementById("conversation")?.append(card);
    return card;
}


async function patchAction(card, action) {
    const patchId = card.dataset.patchId;
    const response = await fetch(`/patches/${encodeURIComponent(patchId)}/${action}`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || data.detail || "Patch action failed.");
    card.dataset.patchStatus = data.status;
    card.querySelector(".patch-heading strong").textContent = data.status.toUpperCase();
    card.querySelector(".patch-actions")?.remove();
    if (data.test) {
        const result = document.createElement("pre");
        result.className = `patch-test ${data.test.passed ? "passed" : "failed"}`;
        result.textContent = `${data.test.passed ? "✓ Changes applied — tests passed" : "✗ Changes applied — tests failed"}\n${data.test.output}`;
        card.append(result);
    }
}


document.addEventListener("click", event => {
    const card = event.target.closest(".patch-card");
    if (!card) return;
    const action = event.target.closest(".patch-apply") ? "apply" : event.target.closest(".patch-reject") ? "reject" : "";
    if (!action) return;
    event.target.disabled = true;
    patchAction(card, action).catch(error => showNotice(error.message, "error")).finally(() => { event.target.disabled = false; });
});


function selectSavedConversation(id, title) {
    conversationId = id;
    const address = `/?conversation_id=${encodeURIComponent(id)}`;
    history.replaceState(null, "", address);
    document.querySelector(".download-link").href = `/download?conversation_id=${encodeURIComponent(id)}`;
    ensureDownloadLink();
    const list = document.getElementById("chat-history");
    let row = [...list.children].find(element => element.dataset.chatId === id);
    if (!row) {
        row = document.createElement("div");
        row.className = "history-row";
        row.dataset.chatId = id;
        const link = document.createElement("a");
        link.className = "nav-item";
        link.href = address;
        const copy = document.createElement("span");
        copy.className = "nav-item-copy";
        const label = document.createElement("strong");
        label.textContent = title;
        copy.append(label);
        link.append(copy);
        const form = document.createElement("form");
        form.className = "delete-chat";
        form.method = "post";
        form.action = `/conversations/${encodeURIComponent(id)}/delete`;
        const active = document.createElement("input");
        active.type = "hidden";
        active.name = "active_id";
        const button = document.createElement("button");
        button.type = "submit";
        button.textContent = "×";
        button.setAttribute("aria-label", `Delete ${title}`);
        form.append(active, button);
        row.append(link, form);
    }
    list.prepend(row);
    list.querySelectorAll(".nav-item").forEach(link => {
        const selected = link === row.querySelector("a");
        link.classList.toggle("active", selected);
        if (selected) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
    });
    list.querySelectorAll('input[name="active_id"]').forEach(input => input.value = id);
    updateConversationTitle(title);
}


async function saveRuntimeSettings() {
    document.getElementById("sidebar-model-name").textContent = modelSelect.options[modelSelect.selectedIndex]?.text || modelSelect.value;
    if (!conversationId) return;
    const body = new FormData();
    body.append("chat_model", modelSelect.value);
    body.append("thinking", String(thinkingToggle.checked));
    body.append("num_ctx", contextSelect.value);
    const response = await fetch(`/conversations/${encodeURIComponent(conversationId)}/settings`, {method: "POST", body});
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Could not save model settings.");
    }
}

document.addEventListener("submit", event => {
    if (event.target.matches(".delete-chat") && !window.confirm("Delete this conversation and all its messages? This cannot be undone.")) {
        event.preventDefault();
    }
});

function renderSources(article, sources) {
    article.querySelector(".answer-sources")?.remove();
    const section = document.createElement("section");
    section.className = "answer-sources";
    section.setAttribute("aria-label", "Sources");
    const heading = document.createElement("h3");
    heading.textContent = "Sources";
    section.append(heading);
    for (const source of sources) {
        if (source.kind === "repository") {
            const label = document.createElement("p");
            label.textContent = `[${source.number}] ${source.reference}`;
            section.append(label);
            continue;
        }
        if (source.kind === "document") {
            const label = document.createElement("p");
            label.textContent = `[${source.number}] ${source.title} — page ${source.page_number}`;
            section.append(label);
            continue;
        }
        const url = new URL(source.url);
        if (!["http:", "https:"].includes(url.protocol)) continue;
        const link = document.createElement("a");
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `[${source.number}] ${source.title} — ${source.domain}`;
        section.append(link);
    }
    article.querySelector(".message-actions").before(section);
}


function resizeTextarea() {
    messageInput.style.height = "auto";
    messageInput.style.height = `${Math.min(messageInput.scrollHeight, 190)}px`;
}


document.querySelectorAll(".markdown-content").forEach(container => {
    renderMarkdown(container, container.textContent.trim());
});

document.querySelectorAll(".prompt-card").forEach(button => {
    button.addEventListener("click", () => {
        messageInput.value = button.dataset.prompt;
        resizeTextarea();
        messageInput.focus();
        messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    });
});

fontButtons.forEach(button => {
    button.addEventListener("click", () => applyFontSize(button.dataset.fontSize));
});

[modelSelect, thinkingToggle, contextSelect].forEach(control => {
    control.addEventListener("change", () => saveRuntimeSettings().catch(error => showNotice(error.message, "error")));
});

menuButton?.addEventListener("click", () => setSidebarOpen(true));
sidebarClose?.addEventListener("click", () => setSidebarOpen(false));
sidebarScrim?.addEventListener("click", () => setSidebarOpen(false));
sidebar?.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", () => setSidebarOpen(false));
});

document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) {
        setSidebarOpen(false);
    }
});

messageInput.addEventListener("input", resizeTextarea);
messageInput.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        chatForm.requestSubmit();
    }
});

window.addEventListener("scroll", () => {
    if (isNearPageBottom()) {
        unseenLatest = false;
    }
    updateJumpLatest();
}, { passive: true });
jumpLatestButton.addEventListener("click", () => jumpToLatest(true));

chatForm.addEventListener("submit", event => {
    event.preventDefault();
    if (activeController) return;
    const userMessage = messageInput.value.trim();
    if (!userMessage) return;
    const followFromStart = isNearPageBottom();

    const conversation = getOrCreateConversation();
    let user;
    if (failedUserMessage) {
        user = {
            article: failedUserMessage.article,
            messageContent: failedUserMessage.article.querySelector(".message-content"),
        };
        user.messageContent.textContent = userMessage;
        user.article.classList.remove("message-failed");
        failedUserMessage = null;
    } else {
        user = createMessage("user", userMessage);
        conversation.append(user.article);
        rebuildPromptNavigation();
    }

    const assistant = createMessage("assistant");
    conversation.append(assistant.article);
    updateExchangeCount();
    messageInput.value = "";
    resizeTextarea();
    if (followFromStart) jumpToLatest(false);
    else {
        unseenLatest = true;
        updateJumpLatest();
    }

    runGeneration({
        url: "/chat",
        userMessage,
        userArticle: user.article,
        assistantArticle: assistant.article,
        assistantContent: assistant.messageContent,
    });
});

stopButton.addEventListener("click", () => activeController?.abort());

document.addEventListener("click", event => {
    const copyButton = event.target.closest(".copy-answer");
    if (copyButton) {
        const content = copyButton.closest(".message").querySelector(".message-content");
        copyText(content.innerText.trim())
            .then(() => showCopiedFeedback(copyButton, "Copy answer"))
            .catch(() => showTemporaryLabel(copyButton, "Copy failed", "Copy answer"));
        return;
    }

    const regenerateButton = event.target.closest(".regenerate");
    if (regenerateButton && !activeController) {
        const article = regenerateButton.closest(".message");
        const content = article.querySelector(".message-content");
        const originalMarkdown = content.dataset.markdown || content.innerText;
        runGeneration({
            url: "/regenerate",
            assistantArticle: article,
            assistantContent: content,
            originalMarkdown,
        });
    }
});

resizeTextarea();
applyFontSize(document.documentElement.dataset.fontSize, false);
rebuildPromptNavigation();

async function saveDocumentSelection() {
    if (!conversationId) return;
    const body = new FormData();
    body.append('document_ids', JSON.stringify([...selectedDocumentIds]));
    const response = await fetch(`/conversations/${encodeURIComponent(conversationId)}/documents`, {method:'POST', body});
    if (!response.ok) throw new Error('Could not save document selection. Please retry.');
}

function showAttachmentStatus(message, isError = false) {
    documentStatus.textContent = message;
    documentStatus.classList.toggle('error', isError);
    documentStatus.classList.toggle('is-hidden', !message);
}

function renderAttachmentChips() {
    attachmentChips.replaceChildren();
    for (const attachment of knownDocuments.filter(item => selectedDocumentIds.has(item.id) && item.status === 'ready')) {
        const chip = document.createElement('span');
        chip.className = 'attachment-chip';
        chip.dataset.documentId = attachment.id;
        const icon = document.createElement('span');
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = '▱';
        const name = document.createElement('span');
        name.textContent = attachment.filename;
        const detach = document.createElement('button');
        detach.type = 'button';
        detach.textContent = '×';
        detach.disabled = Boolean(activeController);
        detach.setAttribute('aria-label', `Detach ${attachment.filename}`);
        chip.append(icon, name, detach);
        attachmentChips.append(chip);
    }
    attachmentChips.classList.toggle('is-hidden', !attachmentChips.children.length);
    updateGroundingMode();
}

async function refreshDocuments() {
    const response = await fetch('/documents');
    if (!response.ok) throw new Error('Could not load documents.');
    const {documents} = await response.json();
    knownDocuments = documents;
    const ready = new Set(documents.filter(doc => doc.status === 'ready').map(doc => doc.id));
    selectedDocumentIds = new Set([...selectedDocumentIds].filter(id => ready.has(id)));
    documentList.replaceChildren();
    for (const doc of documents) {
        const row = document.createElement('div');
        row.className = 'document-row';
        const label = document.createElement('label');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = doc.id;
        checkbox.checked = selectedDocumentIds.has(doc.id);
        checkbox.dataset.notReady = String(doc.status !== 'ready');
        checkbox.disabled = doc.status !== 'ready' || Boolean(activeController);
        const title = document.createElement('span');
        title.textContent = doc.filename;
        label.append(checkbox, title);
        const status = document.createElement('small');
        status.textContent = doc.status + (doc.error ? ': ' + doc.error : '');
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'text-action remove-document';
        remove.dataset.documentId = doc.id;
        remove.textContent = 'Delete';
        remove.disabled = Boolean(activeController);
        remove.setAttribute('aria-label', `Delete ${doc.filename} from the local library`);
        row.append(label, status, remove);
        documentList.append(row);
    }
    renderAttachmentChips();
    if (documents.some(doc => doc.status === 'processing')) {
        setTimeout(() => refreshDocuments().catch(error => documentStatus.textContent = error.message), 2000);
    }
}

documentList.querySelectorAll('input:disabled').forEach(input => input.dataset.notReady = 'true');
documentList.addEventListener('change', async event => {
    if (!event.target.matches('input[type="checkbox"]')) return;
    if (event.target.checked) selectedDocumentIds.add(event.target.value);
    else selectedDocumentIds.delete(event.target.value);
    renderAttachmentChips();
    try { await saveDocumentSelection(); }
    catch (error) { showAttachmentStatus(error.message, true); }
});
documentList.addEventListener('click', async event => {
    const button = event.target.closest('.remove-document');
    if (!button || !confirm('Delete this document from the local library and detach it from every chat? Saved answers keep their cited excerpts.')) return;
    try {
        const response = await fetch(`/documents/${encodeURIComponent(button.dataset.documentId)}/delete`, {method:'POST'});
        if (!response.ok) throw new Error('Could not remove the document. Please retry.');
        selectedDocumentIds.delete(button.dataset.documentId);
        await refreshDocuments();
    } catch (error) { showAttachmentStatus(error.message, true); }
});

attachmentChips.addEventListener('click', async event => {
    const button = event.target.closest('button');
    const chip = button?.closest('.attachment-chip');
    if (!chip || activeController) return;
    selectedDocumentIds.delete(chip.dataset.documentId);
    renderAttachmentChips();
    const checkbox = documentList.querySelector(`input[value="${CSS.escape(chip.dataset.documentId)}"]`);
    if (checkbox) checkbox.checked = false;
    try {
        await saveDocumentSelection();
        showAttachmentStatus('File detached from this conversation.');
    } catch (error) {
        selectedDocumentIds.add(chip.dataset.documentId);
        renderAttachmentChips();
        if (checkbox) checkbox.checked = true;
        showAttachmentStatus(error.message, true);
    }
});

attachmentButton.addEventListener('click', () => attachmentInput.click());
attachmentInput.addEventListener('change', async () => {
    const file = attachmentInput.files[0];
    if (!file || file.size > 20 * 1024 * 1024) {
        showAttachmentStatus('Choose a PDF, TXT or MD file up to 20 MB.', true);
        attachmentInput.value = '';
        return;
    }
    attachmentButton.disabled = true;
    showAttachmentStatus(`Preparing ${file.name} locally…`);
    try {
        const body = new FormData();
        body.append('file', file);
        body.append('conversation_id', conversationId);
        const response = await fetch('/documents', {method:'POST', body});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Document processing failed.');
        selectedDocumentIds.add(result.id);
        await saveDocumentSelection();
        showAttachmentStatus(`${result.filename} is attached and ready.`);
    } catch (error) { showAttachmentStatus(error.message, true); }
    finally {
        attachmentButton.disabled = false;
        attachmentInput.value = '';
        await refreshDocuments().catch(error => showAttachmentStatus(error.message, true));
    }
});
refreshDocuments().catch(error => showAttachmentStatus(error.message, true));

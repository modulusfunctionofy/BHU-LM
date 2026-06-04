// ============================================================
// BHU-LM | user.js
// User interface logic
// ============================================================

"MAX_IMAGE_RETRIEVAL";//MAX_IMAGE_RETRIEVAL
// ===================== image count control ===================== 
var MAX_IMAGE_RETRIEVE = 3;

function getImgCountInput() {
    return document.getElementById('img-count-input');
}

function getImgCountWrap() {
    return document.getElementById('img-count-wrap');
}

function validateImgCount(showMessage) {
    var input = getImgCountInput();
    if (!input) return 1;

    var count = parseInt(input.value, 10);

    if (isNaN(count) || count < 1) {
        count = 1;
        input.value = '1';
    }

    if (count > MAX_IMAGE_RETRIEVE) {
        count = MAX_IMAGE_RETRIEVE;
        input.value = String(MAX_IMAGE_RETRIEVE);
        input.classList.add('error');

        if (showMessage) {
            setStatus('Image count is capped at 3 for now.', 'error');
        }
    } else {
        input.classList.remove('error');
        if (showMessage) {
            setStatus('', '');
        }
    }

    return count;
}



// --- Auth guard ---
(function() {
    if (!localStorage.getItem('bhu_loggedin') || localStorage.getItem('bhu_role') !== 'user') {
        window.location.href = 'index.html';
    }
})();

// --- Display username ---
document.getElementById('topbar-username').textContent = localStorage.getItem('bhu_username') || 'User';

// --- Logout ---
function doLogout() {
    localStorage.removeItem('bhu_loggedin');
    localStorage.removeItem('bhu_role');
    localStorage.removeItem('bhu_username');
    window.location.href = 'index.html';
}

// --- Sidebar toggle ---
var sidebarEl = document.getElementById('sidebar');
var overlayEl = document.getElementById('sidebar-overlay');

document.getElementById('hamburger-btn').addEventListener('click', function() {
    sidebarEl.classList.add('open');
    overlayEl.classList.add('open');
});

function closeSidebar() {
    sidebarEl.classList.remove('open');
    overlayEl.classList.remove('open');
}

// --- Tab state ---
var activeTab = 'mediawiki';
var activeCatId = null;
var activeCatName = '';

// --- Switch tab (Mediawiki / PDFdoc) ---
function switchTab(tab) {
    if (activeTab === tab) return;
    activeTab = tab;

    document.getElementById('tab-mediawiki').classList.toggle('active', tab === 'mediawiki');
    document.getElementById('tab-pdfdoc').classList.toggle('active', tab === 'pdfdoc');
    document.getElementById('cat-header-label').textContent = tab === 'mediawiki' ? 'Mediawiki' : 'PDF Docs';

    activeCatId = null;
    activeCatName = '';
    document.getElementById('active-cat-name').textContent = 'None selected';

    loadCategories();
    clearChunks();
    clearImages();
    setStatus('', '');
}

// --- Get categories from localStorage ---
function getCategories() {
    var key = activeTab === 'mediawiki' ? 'bhu_mw_cats' : 'bhu_pdf_cats';
    var raw = localStorage.getItem(key);
    if (raw) {
        try { return JSON.parse(raw); } catch(e) {}
    }
    // Default starter data
    if (activeTab === 'mediawiki') {
        return [
            { id: 'cat_mw_1', name: '1-Hostel' },
            { id: 'cat_mw_2', name: '2-Academics' }
        ];
    }
    return [];
}

// --- Render category list ---
function loadCategories() {
    var cats = getCategories();
    var listEl = document.getElementById('cat-list');
    listEl.innerHTML = '';

    if (cats.length === 0) {
        listEl.innerHTML = '<div class="cat-empty">No categories yet.</div>';
        return;
    }

    cats.forEach(function(cat) {
        var div = document.createElement('div');
        div.className = 'cat-item' + (cat.id === activeCatId ? ' active' : '');
        div.textContent = cat.name;
        div.onclick = function() { selectCategory(cat.id, cat.name); };
        listEl.appendChild(div);
    });
}

// --- Select category ---
function selectCategory(catId, catName) {
    activeCatId = catId;
    activeCatName = catName;
    document.getElementById('active-cat-name').textContent = catName;
    loadCategories();
    clearChunks();
    clearImages();
    setStatus('', '');
}

// --- Escape HTML ---
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// --- Render chunks ---
function clearChunks() {
    var scroll = document.getElementById('chunks-scroll');
    scroll.innerHTML =
        '<div class="empty-state" id="empty-state">' +
        '<div class="empty-icon">&#128269;</div>' +
        '<p>Select a category and enter a query below to retrieve document chunks.</p>' +
        '</div>';
}

function renderChunks(chunks) {
    var scroll = document.getElementById('chunks-scroll');
    scroll.innerHTML = '';

    if (!chunks || chunks.length === 0) {
        scroll.innerHTML =
            '<div class="empty-state"><div class="empty-icon">&#128270;</div>' +
            '<p>No matching chunks found for this query.</p></div>';
        return;
    }

    chunks.forEach(function(chunk) {
        var card = document.createElement('div');
        card.className = 'chunk-card';
        card.innerHTML =
            '<div class="chunk-meta">' +
            '<span class="chunk-score">score: ' + chunk.score.toFixed(3) + '</span>' +
            '<span class="chunk-source">' + escapeHtml(chunk.source_file) +
            ' &nbsp;|&nbsp; chunk #' + escapeHtml(String(chunk.chunk_id)) + '</span>' +
            '</div>' +
            '<div class="chunk-text">' + escapeHtml(chunk.text) + '</div>';
        scroll.appendChild(card);
    });
}

// --- Image slots ---
function clearImages() {
    for (var i = 0; i < 10; i++) {
        var slot = document.querySelector('.img-slot[data-slot="' + i + '"]');
        var img = document.getElementById('rimg-' + i);
        var label = document.getElementById('rimg-label-' + i);
        if (slot) slot.classList.add('hidden');
        if (img) img.src = '';
        if (label) label.textContent = '';
    }
}

function populateImages(imageList) {
    clearImages();
    var limit = Math.min(imageList.length, 10);
    for (var i = 0; i < limit; i++) {
        var slot = document.querySelector('.img-slot[data-slot="' + i + '"]');
        var img = document.getElementById('rimg-' + i);
        var label = document.getElementById('rimg-label-' + i);
        if (!slot) continue;
        if (img) img.src = imageList[i].path || '';
        if (label) label.textContent = imageList[i].label || '';
        slot.classList.remove('hidden');
    }
}

// --- Image toggle ---
function onImgToggle(checkbox) {
    var msgEl = document.getElementById('img-off-msg');
    var countWrap = getImgCountWrap();

    if (checkbox.checked) {
        msgEl.style.display = 'none';
        if (countWrap) countWrap.style.display = 'flex';
        validateImgCount(false);
    } else {
        msgEl.style.display = '';
        if (countWrap) countWrap.style.display = 'none';
        clearImages();
        setStatus('', '');
    }
}

// --- MMR toggle ---
function onMMRToggle(checkbox) {
    // MMR state will be sent to backend with next query
}

// --- Status text ---
function setStatus(msg, type) {
    var el = document.getElementById('status-text');
    el.textContent = msg;
    el.className = 'status-text' + (type ? ' ' + type : '');
}

// --- Send query ---
function sendQuery() {
    var queryInput = document.getElementById('query-input');
    var query = queryInput.value.trim();

    if (!query) {
        queryInput.focus();
        return;
    }

    if (!activeCatId) {
        setStatus('Please select a category first.', 'error');
        return;
    }

    var mmr = document.getElementById('mmr-toggle').checked ? 1 : 0;
    var imgOn = document.getElementById('img-toggle').checked;
    var imgCount = imgOn ? validateImgCount(true) : 0;
    var sendBtn = document.getElementById('send-btn');

    sendBtn.disabled = true;
    setStatus('Retrieving...', 'loading');

    var scroll = document.getElementById('chunks-scroll');
    scroll.innerHTML =
        '<div class="chunks-loading"><div class="spinner"></div><span>Searching documents...</span></div>';

    // ============================================================
    // BACKEND INTEGRATION POINT
    // Replace this mock with a real fetch() call:
    //
    // fetch('/api/retrieve', {
    //     method: 'POST',
    //     headers: { 'Content-Type': 'application/json' },
    //     body: JSON.stringify({
    //         query: query,
    //         category: activeCatId,
    //         tab: activeTab,
    //         mmr: mmr,
    //         img: imgOn ? 1 : 0
    //     })
    // })
    // .then(function(r) { return r.json(); })
    // .then(function(data) {
    //     renderChunks(data.chunks);
    //     if (imgOn && data.images && data.images.length) {
    //         populateImages(data.images);
    //     }
    //     setStatus(data.chunks.length + ' chunk(s) found.', '');
    //     sendBtn.disabled = false;
    // })
    // .catch(function(err) {
    //     setStatus('Error: ' + err.message, 'error');
    //     sendBtn.disabled = false;
    // });
    // ============================================================

    // Mock response for demo
    setTimeout(function() {
        var mmrLabel = mmr ? 'ON (diversity-optimized)' : 'OFF (relevance-only)';
        var tabLabel = activeTab === 'mediawiki' ? 'MediaWiki' : 'PDF';

        var mockChunks = [
            {
                score: 0.874,
                source_file: 'narendra_modi.html',
                chunk_id: 3,
                text: '[Mock Chunk] Retrieved from ' + tabLabel + ' index.\n' +
                      'Category: ' + activeCatName + '\n' +
                      'MMR: ' + mmrLabel + '\n\n' +
                      'This is a demonstration chunk. In production, this will contain actual document text ' +
                      'from your ChromaDB vector store, retrieved using hybrid dense + BM25 retrieval with ' +
                      'the ' + (mmr ? 'MMR diversity algorithm.' : 'pure relevance ranking.')
            },
            {
                score: 0.792,
                source_file: 'hostel.html',
                chunk_id: 7,
                text: '[Mock Chunk] Hybrid score combines dense vector similarity (weight 0.55) and BM25 ' +
                      'keyword match (weight 0.45).\n\n' +
                      'Your query: "' + query + '"\n\n' +
                      'Real chunks will be populated by RAG_retrieve.py using the embedding model and ' +
                      'chunking strategy configured for this category.'
            },
            {
                score: 0.651,
                source_file: 'hostel.html',
                chunk_id: 12,
                text: '[Mock Chunk] Third result showing layout. Real implementation will show actual indexed ' +
                      'content from your BHU MediaWiki pages or PDF documents.'
            }
        ];

        renderChunks(mockChunks);

        if (imgOn) {
            var mockImages = [
                { path: 'https://placehold.co/200x120/e8eaf6/1a237e?text=Image+1', label: 'narendra_modi/img1.jpg' },
                { path: 'https://placehold.co/200x120/e8eaf6/1a237e?text=Image+2', label: 'hostel/banner.jpg' },
                { path: 'https://placehold.co/200x120/e8eaf6/1a237e?text=Image+3', label: 'hostel/map.jpg' }
            ];

            populateImages(mockImages.slice(0, imgCount));
        }

        setStatus(mockChunks.length + ' chunks retrieved.', '');
        sendBtn.disabled = false;
    }, 800);
}

// --- Enter key in textarea ---
document.getElementById('query-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuery();
    }
});

// --- Init ---
loadCategories();

//image counter hidden
var imgCountWrap = getImgCountWrap();
if (imgCountWrap) imgCountWrap.style.display = 'none';
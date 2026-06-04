// ============================================================
// BHU-LM | admin.js
// Admin interface logic
// ============================================================

// --- Auth guard ---
(function() {
    if (!localStorage.getItem('bhu_loggedin') || localStorage.getItem('bhu_role') !== 'admin') {
        window.location.href = 'index.html';
    }
})();

document.getElementById('topbar-username').textContent = localStorage.getItem('bhu_username') || 'Admin';

// --- Constants ---
var DEFAULT_REMOVE_CLASSES = [
    'infobox', 'sidebar', 'navbox', 'vertical-navbox',
    'portable-infobox', 'reflist', 'toc', 'hatnote',
    'mw-editsection', 'mw-references-wrap'
];

var DEFAULT_NOISE_SUBSTRINGS = [
    'reference', 'see also', 'further reading', 'external link',
    'bibliography', 'notes', 'sources', 'citation'
];

var OPTION_LABELS = {
    '1': 'Fast (OPTION 1)',
    '2': 'Efficient (OPTION 2)',
    '3': 'Accurate (OPTION 3)'
};

var OPTION_DETAIL = {
    '1': 'nomic-embed-text · title chunking',
    '2': 'snowflake-arctic-embed · title chunking',
    '3': 'snowflake-arctic-embed · semantic chunking'
};

var IMG_LABELS = {
    '0': 'Off',
    '1': 'Fast — CLIP',
    '2': 'Accurate — Gemini LLM'
};

// --- Sidebar ---
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

// --- Logout ---
function doLogout() {
    localStorage.removeItem('bhu_loggedin');
    localStorage.removeItem('bhu_role');
    localStorage.removeItem('bhu_username');
    window.location.href = 'index.html';
}

// --- Tab state ---
var activeTab = 'mediawiki';
var activeCatId = null;

function switchTab(tab) {
    if (activeTab === tab) return;
    activeTab = tab;
    activeCatId = null;

    document.getElementById('tab-mediawiki').classList.toggle('active', tab === 'mediawiki');
    document.getElementById('tab-pdfdoc').classList.toggle('active', tab === 'pdfdoc');
    document.getElementById('cat-header-label').textContent = tab === 'mediawiki' ? 'Mediawiki' : 'PDF Docs';

    loadCategories();
    showAdminEmpty();
}

//something
var MASTER_LOCK_CACHE = null;

async function fetchMasterLock() {
    if (MASTER_LOCK_CACHE !== null) return MASTER_LOCK_CACHE;

    try {
        var res = await fetch('./media_extration/Master_lock.json', { cache: 'no-store' });
        if (!res.ok) {
            MASTER_LOCK_CACHE = {};
            return MASTER_LOCK_CACHE;
        }
        MASTER_LOCK_CACHE = await res.json();
        return MASTER_LOCK_CACHE || {};
    } catch (e) {
        MASTER_LOCK_CACHE = {};
        return MASTER_LOCK_CACHE;
    }
}

function isCategoryLocked(lockData, categoryName) {
    if (!lockData) return false;

    var entry = null;

    if (Array.isArray(lockData)) {
        entry = lockData.find(function(item) {
            return item && (
                item.category === categoryName ||
                item.name === categoryName ||
                item.cat === categoryName
            );
        });
    } else if (typeof lockData === 'object') {
        entry = lockData[categoryName] || lockData[String(categoryName)] || null;
    }

    if (typeof entry === 'boolean') return entry;
    if (typeof entry === 'string') return entry === 'True' || entry === 'true';

    if (entry && typeof entry === 'object') {
        return (
            entry.locked === true ||
            entry.locked === 'True' ||
            entry.locked === 'true' ||
            entry.value === true ||
            entry.value === 'True' ||
            entry.value === 'true' ||
            entry.text_processing === true ||
            entry.image_processing === true
        );
    }

    return false;
}

function setProcessingLockState(prefix, locked) {
    var optGroup = document.getElementById(prefix + '-option-group');
    var optLockMsg = document.getElementById(prefix + '-option-lock-msg');
    var optLockNote = document.getElementById(prefix + '-option-lock-note');
    var optWarn = document.getElementById(prefix + '-option-warn');

    var imgGroup = document.getElementById(prefix + '-img-group');
    var imgLockMsg = document.getElementById(prefix + '-img-lock-msg');
    var imgLockNote = document.getElementById(prefix + '-img-lock-note');

    function toggleGroup(groupEl) {
        if (!groupEl) return;
        var inputs = groupEl.querySelectorAll('input[type="radio"]');
        inputs.forEach(function(input) {
            input.disabled = locked;
        });
        groupEl.classList.toggle('processing-locked', locked);
    }

    toggleGroup(optGroup);
    toggleGroup(imgGroup);

    if (optLockMsg) {
        optLockMsg.classList.toggle('hidden', !locked);
        optLockMsg.textContent = locked ? 'Text Processing is locked for this category.' : '';
    }
    if (optLockNote) {
        optLockNote.classList.toggle('hidden', !locked);
    }
    if (optWarn) {
        optWarn.classList.toggle('hidden', locked);
    }

    if (imgLockMsg) {
        imgLockMsg.classList.toggle('hidden', !locked);
        imgLockMsg.textContent = locked ? 'Image Processing is locked for this category.' : '';
    }
    if (imgLockNote) {
        imgLockNote.classList.toggle('hidden', !locked);
    }
}

// --- Data helpers ---
function getCatKey() {
    return activeTab === 'mediawiki' ? 'bhu_mw_cats' : 'bhu_pdf_cats';
}

function getCategories() {
    var raw = localStorage.getItem(getCatKey());
    if (raw) {
        try { return JSON.parse(raw); } catch(e) {}
    }
    
    // Default starter data for demo
    if (activeTab === 'mediawiki') {
        var defaults = [
            {
                id: 'cat_mw_1',
                name: '1-Hostel',
                locked_option: null,
                locked_img_option: null,
                docs: [
                    { name: 'narendra_modi', added: '2025-03-05' },
                    { name: 'hostel', added: '2025-03-05' }
                ],
                settings: {
                    option: 1,
                    image_option: 0,
                    image_retrieve: 3,
                    min_chunks: 3,
                    max_chunks: 10,
                    remove_classes: DEFAULT_REMOVE_CLASSES.slice(),
                    noise_substrings: DEFAULT_NOISE_SUBSTRINGS.slice()
                },
                db: {
                    text_path: 'databases/1-Hostel/chroma_db/',
                    image_paths: {}
                }
            }
        ];
        saveCategories(defaults);
        return defaults;
    }
    return [];
}

function saveCategories(cats) {
    localStorage.setItem(getCatKey(), JSON.stringify(cats));
}

function getCatById(id) {
    return getCategories().find(function(c) { return c.id === id; }) || null;
}

function updateCat(updated) {
    var cats = getCategories();
    var idx = cats.findIndex(function(c) { return c.id === updated.id; });
    if (idx !== -1) {
        cats[idx] = updated;
        saveCategories(cats);
    }
}

// --- Category sidebar ---
function loadCategories() {
    var cats = getCategories();
    var listEl = document.getElementById('cat-list');
    listEl.innerHTML = '';

    if (cats.length === 0) {
        listEl.innerHTML = '<div class="cat-empty">No categories yet.<br>Use + below.</div>';
        return;
    }

    cats.forEach(function(cat) {
        var row = document.createElement('div');
        row.className = 'cat-item-row';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cat-item-btn' + (cat.id === activeCatId ? ' active' : '');
        btn.innerHTML = escapeHtml(cat.name) + ((cat.locked_option === 3) ? ' &#128274;' : '');
        btn.onclick = function() { selectCategory(cat.id); };

        var del = document.createElement('button');
        del.type = 'button';
        del.className = 'cat-delete-btn';
        del.title = 'Delete category';
        del.setAttribute('aria-label', 'Delete category');
        del.innerHTML = '&#10005;';
        del.onclick = function(e) {
            e.stopPropagation();
            deleteCategory(cat.id);
        };

        row.appendChild(btn);
        row.appendChild(del);
        listEl.appendChild(row);
    });
}

//delete button function for Categories section 
function deleteCategory(catId) {
    var cat = getCatById(catId);
    if (!cat) return;

    if (!confirm('Delete category "' + cat.name + '" permanently?')) {
        return;
    }

    var cats = getCategories().filter(function(c) {
        return c.id !== catId;
    });

    saveCategories(cats);

    if (activeCatId === catId) {
        activeCatId = null;
        showAdminEmpty();
    }

    loadCategories();
}

function selectCategory(catId) {
    activeCatId = catId;
    loadCategories();

    var cat = getCatById(catId);
    if (!cat) return;

    showCatDetail(cat);
}

// --- Show/hide admin content ---
function showAdminEmpty() {
    document.getElementById('admin-empty').classList.remove('hidden');
    document.getElementById('cat-detail').classList.add('hidden');
}

function showCatDetail(cat) {
    document.getElementById('admin-empty').classList.add('hidden');
    var detail = document.getElementById('cat-detail');
    detail.classList.remove('hidden');

    // Category name + lock badge
    document.getElementById('cat-detail-name').textContent = cat.name;
    var lockBadge = document.getElementById('cat-lock-badge');
    if (cat.locked_option === 3) {
        lockBadge.textContent = 'LOCKED — OPTION 3';
        lockBadge.className = 'badge badge-orange';
    } else {
        lockBadge.textContent = '';
        lockBadge.className = '';
    }

    renderSettingsPanel(cat);
    renderDocsPanel(cat);
    renderAdminImages(cat);
}

function renderSettingsPanel(cat) {
    var body = document.getElementById('settings-panel-body');
    var s = cat.settings || {};

    var option = s.option || 1;
    var imgOption = s.image_option !== undefined ? s.image_option : 0;

    body.innerHTML = '';

    function addRow(key, val, sub) {
        var row = document.createElement('div');
        row.className = 'setting-row';
        row.innerHTML =
            '<div class="setting-key">' + escapeHtml(key) + '</div>' +
            '<div class="setting-val">' + escapeHtml(String(val)) + '</div>' +
            (sub ? '<div class="text-small text-muted mt-4">' + escapeHtml(sub) + '</div>' : '');
        body.appendChild(row);
    }

    addRow('Text Processing', OPTION_LABELS[String(option)] || ('OPTION ' + option), OPTION_DETAIL[String(option)] || '');
    addRow('Image Processing', IMG_LABELS[String(imgOption)] || ('IMG_OPTION ' + imgOption));

    if (imgOption !== 0) {
        addRow('Image Retrieve', (s.image_retrieve || 3) + ' images');
    }

    addRow('Min Chunks', s.min_chunks || 3);
    addRow('Max Chunks', s.max_chunks || 10);

    if (cat.locked_option) {
        var lockRow = document.createElement('div');
        lockRow.className = 'setting-row';
        lockRow.innerHTML = '<span class="badge badge-orange">&#128274; Locked to OPTION ' + cat.locked_option + '</span>';
        body.appendChild(lockRow);
    }

    if (activeTab === 'mediawiki') {
        var classCount = (s.remove_classes || []).length;
        var classList = (s.remove_classes || []).slice(0, 3).join(', ');
        if (classCount > 3) classList += '...';
        addRow('Classes removed', classCount + ' classes', classList);
        addRow('Sections removed', (s.noise_substrings || []).length + ' substrings');
    }
}

function renderDocsPanel(cat) {
    var docsList = document.getElementById('docs-list');
    var dbInfo = document.getElementById('db-info');

    docsList.innerHTML = '';
    if (!cat.docs || cat.docs.length === 0) {
        docsList.innerHTML = '<div class="cat-empty">No documents yet. Use "+ Add More".</div>';
    } else {
        cat.docs.forEach(function(doc) {
            var entry = document.createElement('div');
            entry.className = 'doc-entry';
            entry.innerHTML =
                '<span class="doc-arrow">&#8594;</span>' +
                '<span class="doc-name">' + escapeHtml(doc.name) + '</span>' +
                '<span class="text-small text-muted">' + (doc.added || '') + '</span>';
            docsList.appendChild(entry);
        });
    }

    dbInfo.innerHTML = '';
    var db = cat.db || {};
    var dbRows = [];

    if (db.text_path) {
        dbRows.push({ key: 'text/db', path: db.text_path });
    } else {
        dbRows.push({ key: 'text/db', path: 'Not yet initialized' });
    }

    var imgPaths = db.image_paths || {};
    Object.keys(imgPaths).forEach(function(docName) {
        dbRows.push({ key: 'img/' + docName, path: imgPaths[docName] });
    });

    if (dbRows.length === 0) {
        dbInfo.innerHTML = '<div class="cat-empty">No database info yet.</div>';
    } else {
        dbRows.forEach(function(row) {
            var entry = document.createElement('div');
            entry.className = 'db-entry';
            entry.innerHTML =
                '<span class="db-key">' + escapeHtml(row.key) + '</span>' +
                '<span class="db-path">' + escapeHtml(row.path) + '</span>';
            dbInfo.appendChild(entry);
        });
    }
}

function renderAdminImages(cat) {
    var imgBody = document.getElementById('admin-img-body');
    imgBody.innerHTML = '';

    var imgOption = (cat.settings || {}).image_option || 0;

    if (imgOption === 0) {
        imgBody.innerHTML = '<p class="img-off-msg">Image processing is off for this category.</p>';
        return;
    }

    var docs = cat.docs || [];
    if (docs.length === 0) {
        imgBody.innerHTML = '<p class="img-off-msg">No images yet.</p>';
        return;
    }

    docs.forEach(function(doc) {
        var wrap = document.createElement('div');
        var img = document.createElement('img');
        var label = document.createElement('div');
        img.src = 'https://placehold.co/140x80/e8eaf6/1a237e?text=' + encodeURIComponent(doc.name);
        img.className = 'admin-thumb';
        img.alt = doc.name;
        label.className = 'admin-thumb-label';
        label.textContent = doc.name;
        wrap.appendChild(img);
        wrap.appendChild(label);
        imgBody.appendChild(wrap);
    });
}

// ============================================================
// NEW CATEGORY MODAL
// ============================================================
function openNewCatModal() {
    closeSidebar();
    document.getElementById('new-cat-name').value = '';
    openModal('new-cat-modal');
}

function createCategory() {
    var nameInput = document.getElementById('new-cat-name');
    var name = nameInput.value.trim();
    if (!name) {
        nameInput.focus();
        return;
    }

    var cats = getCategories();
    var id = 'cat_' + (activeTab === 'mediawiki' ? 'mw' : 'pdf') + '_' + Date.now();

    var newCat = {
        id: id,
        name: name,
        locked_option: null,
        locked_img_option: null,
        docs: [],
        settings: {
            option: 1,
            image_option: 0,
            image_retrieve: 3,
            min_chunks: 3,
            max_chunks: 10,
            remove_classes: DEFAULT_REMOVE_CLASSES.slice(),
            noise_substrings: DEFAULT_NOISE_SUBSTRINGS.slice()
        },
        db: {
            text_path: '',
            image_paths: {}
        }
    };

    cats.push(newCat);
    saveCategories(cats);
    closeModal('new-cat-modal');
    loadCategories();
    selectCategory(id);
}

// ============================================================
// ADD MORE MODAL — MEDIAWIKI
// ============================================================
async function openAddMoreModal() {
    if (!activeCatId) return;
    var cat = getCatById(activeCatId);
    if (!cat) return;

    if (activeTab === 'mediawiki') {
        await openAddMoreMW(cat);
    } else {
        await openAddMorePDF(cat);
    }
}

async function openAddMoreMW(cat) {
    document.getElementById('addmore-mw-catname').textContent = cat.name;
    document.getElementById('mw-pages').value = '';
    document.getElementById('mw-min-chunks').value = cat.settings.min_chunks || 3;
    document.getElementById('mw-max-chunks').value = cat.settings.max_chunks || 10;
    document.getElementById('mw-img-retrieve').value = cat.settings.image_retrieve || 3;

    var optGroup = document.getElementById('mw-option-group');
    var imgGroup = document.getElementById('mw-img-group');

    var optRadios = optGroup.querySelectorAll('input[type="radio"]');
    var imgRadios = imgGroup.querySelectorAll('input[type="radio"]');

    optRadios.forEach(function(r) {
        r.disabled = false;
        r.checked = r.value === String(cat.settings.option || 1);
    });

    imgRadios.forEach(function(r) {
        r.disabled = false;
        r.checked = r.value === String(cat.settings.image_option || 0);
    });

    if (typeof onMwOptionChange === 'function') onMwOptionChange();
    if (typeof onMwImgChange === 'function') onMwImgChange();

    var lockData = await fetchMasterLock();
    var locked = isCategoryLocked(lockData, cat.name);

    setProcessingLockState('mw', locked);

    openModal('addmore-mw-modal');
}

function onMwOptionChange() {
    var selected = document.querySelector('input[name="mw-option"]:checked');
    var warnEl = document.getElementById('mw-option-warn');
    if (selected && selected.value === '3') {
        warnEl.classList.remove('hidden');
    } else {
        warnEl.classList.add('hidden');
    }
}

function onMwImgChange() {
    var selected = document.querySelector('input[name="mw-img"]:checked');
    var row = document.getElementById('mw-img-retrieve-row');
    if (selected && selected.value !== '0') {
        row.classList.remove('hidden');
    } else {
        row.classList.add('hidden');
    }
}

function submitAddMoreMW() {
    var cat = getCatById(activeCatId);
    if (!cat) return;

    var pages = document.getElementById('mw-pages').value.trim();
    if (!pages) {
        alert('Please enter at least one wiki page name.');
        return;
    }

    var pageList = pages.split('\n').map(function(p) { return p.trim(); }).filter(Boolean);
    var optionVal = parseInt(document.querySelector('input[name="mw-option"]:checked').value);
    var imgOption = parseInt(document.querySelector('input[name="mw-img"]:checked').value);
    var imgRetrieve = parseInt(document.getElementById('mw-img-retrieve').value) || 3;
    var minChunks = parseInt(document.getElementById('mw-min-chunks').value) || 3;
    var maxChunks = parseInt(document.getElementById('mw-max-chunks').value) || 10;

    var removeClasses = getTagValues('mw-remove-classes', 'mw-classes-input');
    var noiseSubstrings = getTagValues('mw-noise-substrings', 'mw-noise-input');

    var today = new Date().toISOString().split('T')[0];

    pageList.forEach(function(p) {
        var safeName = p.replace(/ /g, '_').toLowerCase();
        var exists = cat.docs.find(function(d) { return d.name === safeName; });
        if (!exists) {
            cat.docs.push({ name: safeName, added: today, original: p });
        }
    });

    cat.settings.option = optionVal;
    cat.settings.image_option = imgOption;
    cat.settings.image_retrieve = imgRetrieve;
    cat.settings.min_chunks = minChunks;
    cat.settings.max_chunks = maxChunks;
    cat.settings.remove_classes = removeClasses;
    cat.settings.noise_substrings = noiseSubstrings;

    if (optionVal === 3 && !cat.locked_option) {
        cat.locked_option = 3;
    }
    if (imgOption !== 0 && cat.locked_img_option === null) {
        cat.locked_img_option = imgOption;
    }

    cat.db.text_path = 'databases/' + cat.name + '/chroma_db/';
    pageList.forEach(function(p) {
        var safeName = p.replace(/ /g, '_').toLowerCase();
        if (imgOption !== 0) {
            cat.db.image_paths[safeName] = 'image_processed/' + cat.name + '/' + safeName + '/';
        }
    });

    updateCat(cat);
    closeModal('addmore-mw-modal');
    showCatDetail(cat);

    alert('Documents queued for processing!\n\nBackend pipeline will run:\n1. get_html.py → fetch pages\n2. clean_html.py → remove noise\n3. RAG.py → chunk & embed\n4. image_extraction.py → extract images\n5. image_process.py → process images');
}

// ============================================================
// ADD MORE MODAL — PDF
// ============================================================
function openAddMorePDF(cat) {
    document.getElementById('addmore-pdf-catname').textContent = cat.name;
    document.getElementById('pdf-min-chunks').value = cat.settings.min_chunks || 3;
    document.getElementById('pdf-max-chunks').value = cat.settings.max_chunks || 10;
    document.getElementById('pdf-img-retrieve').value = cat.settings.image_retrieve || 3;

    var optGroup = document.getElementById('pdf-option-group');
    var optLockEl = document.getElementById('pdf-option-lock-msg');
    var optWarnEl = document.getElementById('pdf-option-warn');
    var radios = optGroup.querySelectorAll('input[type="radio"]');

    if (cat.locked_option) {
        radios.forEach(function(r) {
            r.disabled = true;
            if (r.value === String(cat.locked_option)) r.checked = true;
        });
        optLockEl.innerHTML = '&#128274; Category is locked to ' + OPTION_LABELS[String(cat.locked_option)];
        optLockEl.classList.remove('hidden');
        optLockEl.classList.add('locked');
        optWarnEl.classList.add('hidden');
    } else {
        radios.forEach(function(r) {
            r.disabled = false;
            if (r.value === String(cat.settings.option || 1)) r.checked = true;
        });
        optLockEl.classList.add('hidden');
        onPdfOptionChange();
    }

    var imgGroup = document.getElementById('pdf-img-group');
    var imgLockEl = document.getElementById('pdf-img-lock-msg');
    var imgRadios = imgGroup.querySelectorAll('input[type="radio"]');

    if (cat.locked_img_option !== null && cat.locked_img_option !== undefined) {
        imgRadios.forEach(function(r) {
            r.disabled = true;
            if (r.value === String(cat.locked_img_option)) r.checked = true;
        });
        imgLockEl.innerHTML = '&#128274; Image processing is locked to ' + IMG_LABELS[String(cat.locked_img_option)];
        imgLockEl.classList.remove('hidden');
        imgLockEl.classList.add('locked');
    } else {
        imgRadios.forEach(function(r) {
            r.disabled = false;
            if (r.value === String(cat.settings.image_option || 0)) r.checked = true;
        });
        imgLockEl.classList.add('hidden');
    }

    onPdfImgChange();
    openModal('addmore-pdf-modal');
}

function onPdfOptionChange() {
    var selected = document.querySelector('input[name="pdf-option"]:checked');
    var warnEl = document.getElementById('pdf-option-warn');
    if (selected && selected.value === '3') {
        warnEl.classList.remove('hidden');
    } else {
        warnEl.classList.add('hidden');
    }
}

function onPdfImgChange() {
    var selected = document.querySelector('input[name="pdf-img"]:checked');
    var row = document.getElementById('pdf-img-retrieve-row');
    if (selected && selected.value !== '0') {
        row.classList.remove('hidden');
    } else {
        row.classList.add('hidden');
    }
}

function submitAddMorePDF() {
    var cat = getCatById(activeCatId);
    if (!cat) return;

    var fileInput = document.getElementById('pdf-files');
    if (!fileInput.files || fileInput.files.length === 0) {
        alert('Please select at least one PDF file.');
        return;
    }

    var optionVal = parseInt(document.querySelector('input[name="pdf-option"]:checked').value);
    var imgOption = parseInt(document.querySelector('input[name="pdf-img"]:checked').value);
    var imgRetrieve = parseInt(document.getElementById('pdf-img-retrieve').value) || 3;
    var minChunks = parseInt(document.getElementById('pdf-min-chunks').value) || 3;
    var maxChunks = parseInt(document.getElementById('pdf-max-chunks').value) || 10;

    var today = new Date().toISOString().split('T')[0];

    Array.from(fileInput.files).forEach(function(f) {
        var safeName = f.name.replace('.pdf', '').replace(/[^a-zA-Z0-9_-]/g, '_').toLowerCase();
        var exists = cat.docs.find(function(d) { return d.name === safeName; });
        if (!exists) {
            cat.docs.push({ name: safeName, added: today, original: f.name });
        }
    });

    cat.settings.option = optionVal;
    cat.settings.image_option = imgOption;
    cat.settings.image_retrieve = imgRetrieve;
    cat.settings.min_chunks = minChunks;
    cat.settings.max_chunks = maxChunks;

    if (optionVal === 3 && !cat.locked_option) {
        cat.locked_option = 3;
    }
    if (imgOption !== 0 && cat.locked_img_option === null) {
        cat.locked_img_option = imgOption;
    }

    cat.db.text_path = 'databases/' + cat.name + '/chroma_db/';

    updateCat(cat);
    closeModal('addmore-pdf-modal');
    showCatDetail(cat);

    alert('PDF documents queued for processing!');
}

// ============================================================
// TAGS COMPONENT
// ============================================================
function initTags(containerId, inputId, initialValues) {
    var container = document.getElementById(containerId);
    var inputEl = document.getElementById(inputId);

    var existingTags = container.querySelectorAll('.tag');
    existingTags.forEach(function(t) { t.remove(); });

    initialValues.forEach(function(val) {
        addTagToContainer(container, inputEl, val);
    });

    inputEl.onkeydown = function(e) {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            var val = inputEl.value.trim().replace(/,/g, '');
            if (val) {
                addTagToContainer(container, inputEl, val);
                inputEl.value = '';
            }
        }
    };
}

function addTagToContainer(container, inputEl, value) {
    var tag = document.createElement('span');
    tag.className = 'tag';
    tag.innerHTML = escapeHtml(value) + '<button class="tag-remove" onclick="this.parentElement.remove()" title="Remove">&times;</button>';
    container.insertBefore(tag, inputEl);
}

function getTagValues(containerId, inputId) {
    var container = document.getElementById(containerId);
    var tags = container.querySelectorAll('.tag');
    var values = [];
    tags.forEach(function(t) {
        var text = t.childNodes[0].textContent.trim();
        if (text) values.push(text);
    });
    return values;
}

// ============================================================
// MODAL HELPERS
// ============================================================
function openModal(id) {
    document.getElementById(id).classList.add('open');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) {
            overlay.classList.remove('open');
        }
    });
});

// --- Escape HTML ---
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// --- Init ---
loadCategories();
showAdminEmpty();
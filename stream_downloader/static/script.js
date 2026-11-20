document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const urlForm = document.getElementById('urlForm');
    const videoUrlInput = document.getElementById('videoUrl');
    const pasteBtn = document.getElementById('pasteBtn');
    const fetchBtn = document.getElementById('fetchBtn');
    const fetchSpinner = document.getElementById('fetchSpinner');

    const previewCard = document.getElementById('previewCard');
    const videoThumb = document.getElementById('videoThumb');
    const videoDurationBadge = document.getElementById('videoDurationBadge');
    const videoTitle = document.getElementById('videoTitle');
    const videoChannel = document.getElementById('videoChannel');

    // Tabs
    const tabAiShorts = document.getElementById('tabAiShorts');
    const tabFullDownload = document.getElementById('tabFullDownload');
    const aiModeSection = document.getElementById('aiModeSection');
    const fullModeSection = document.getElementById('fullModeSection');

    // AI Controls
    const aiShortQuality = document.getElementById('aiShortQuality');
    const aiFrameStyle = document.getElementById('aiFrameStyle');
    const aiNumClips = document.getElementById('aiNumClips');
    const aiClipDuration = document.getElementById('aiClipDuration');
    const aiHookStyle = document.getElementById('aiHookStyle');
    const aiEnableOverlay = document.getElementById('aiEnableOverlay');
    const aiOverlayBadge = document.getElementById('aiOverlayBadge');
    const aiCreatorTag = document.getElementById('aiCreatorTag');
    const overlayDetailsRow = document.getElementById('overlayDetailsRow');
    const startAiBtn = document.getElementById('startAiBtn');

    // Toggle Overlay details inputs
    if (aiEnableOverlay && overlayDetailsRow) {
        aiEnableOverlay.addEventListener('change', () => {
            overlayDetailsRow.style.display = aiEnableOverlay.checked ? 'grid' : 'none';
        });
    }

    // Full Download Controls
    const qualityOptions = document.querySelectorAll('.quality-option');
    const startDownloadBtn = document.getElementById('startDownloadBtn');

    // Progress Card
    const progressCard = document.getElementById('progressCard');
    const downloadStatusText = document.getElementById('downloadStatusText');
    const progressPercent = document.getElementById('progressPercent');
    const progressBarFill = document.getElementById('progressBarFill');
    const downloadSpeed = document.getElementById('downloadSpeed');
    const downloadEta = document.getElementById('downloadEta');

    // AI Shorts Results
    const aiShortsCard = document.getElementById('aiShortsCard');
    const aiResultsSubtitle = document.getElementById('aiResultsSubtitle');
    const downloadAllZipBtn = document.getElementById('downloadAllZipBtn');
    const shortsGrid = document.getElementById('shortsGrid');

    // Full Video Complete Card
    const completeCard = document.getElementById('completeCard');
    const downloadedFileName = document.getElementById('downloadedFileName');
    const videoPlayer = document.getElementById('videoPlayer');
    const directDownloadLink = document.getElementById('directDownloadLink');
    const downloadAnotherBtn = document.getElementById('downloadAnotherBtn');

    // History
    const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');
    const downloadsList = document.getElementById('downloadsList');

    // Mobile Toast Notification Helper
    const mobileToast = document.getElementById('mobileToast');
    function showToast(msg, duration = 3000) {
        if (!mobileToast) return;
        mobileToast.textContent = msg;
        mobileToast.classList.add('show');
        setTimeout(() => {
            mobileToast.classList.remove('show');
        }, duration);
    }

    // Share App Public Link (Web Share API for Android/iOS or Clipboard Copy)
    const shareAppBtn = document.getElementById('shareAppBtn');
    if (shareAppBtn) {
        shareAppBtn.addEventListener('click', async () => {
            const currentUrl = window.location.href.split('?')[0];
            if (navigator.share) {
                try {
                    await navigator.share({
                        title: 'StreamGrabber AI',
                        text: 'YouTube Live Streams download karein aur automatic 9:16 viral shorts banayein!',
                        url: currentUrl
                    });
                    showToast('📲 Link shared successfully!');
                    return;
                } catch (e) {
                    // fall through if cancelled
                }
            }
            try {
                await navigator.clipboard.writeText(currentUrl);
                showToast('✅ Public Link Copied! Send to anyone');
            } catch (err) {
                const dummy = document.createElement('input');
                document.body.appendChild(dummy);
                dummy.value = currentUrl;
                dummy.select();
                document.execCommand('copy');
                document.body.removeChild(dummy);
                showToast('✅ Public Link Copied!');
            }
        });
    }

    let currentVideoInfo = null;
    let selectedQuality = "720p";
    let pollInterval = null;

    // 1. Paste from clipboard
    pasteBtn.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) {
                videoUrlInput.value = text.trim();
                fetchVideoInfo();
            }
        } catch (err) {
            videoUrlInput.focus();
        }
    });

    // 2. Tab switching
    tabAiShorts.addEventListener('click', () => {
        tabAiShorts.classList.add('active');
        tabFullDownload.classList.remove('active');
        aiModeSection.style.display = 'block';
        fullModeSection.style.display = 'none';
    });

    tabFullDownload.addEventListener('click', () => {
        tabFullDownload.classList.add('active');
        tabAiShorts.classList.remove('active');
        fullModeSection.style.display = 'block';
        aiModeSection.style.display = 'none';
    });

    // Form submit
    urlForm.addEventListener('submit', (e) => {
        e.preventDefault();
        fetchVideoInfo();
    });

    // Quality selector
    qualityOptions.forEach(opt => {
        opt.addEventListener('click', () => {
            qualityOptions.forEach(o => o.classList.remove('active'));
            opt.classList.add('active');
            const radio = opt.querySelector('input[type="radio"]');
            radio.checked = true;
            selectedQuality = radio.value;
        });
    });

    // 3. Fetch Info
    async function fetchVideoInfo() {
        const url = videoUrlInput.value.trim();
        if (!url) return;

        // Reset display
        previewCard.style.display = 'none';
        progressCard.style.display = 'none';
        completeCard.style.display = 'none';
        aiShortsCard.style.display = 'none';

        fetchSpinner.style.display = 'inline-block';
        fetchBtn.disabled = true;

        try {
            const res = await fetch('/api/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });

            const data = await res.json();
            if (!data.success) {
                alert('Stream Info Fetch Nahi Ho Payi:\n' + (data.error || 'Invalid link'));
                return;
            }

            currentVideoInfo = data;

            videoThumb.src = data.thumbnail || 'https://via.placeholder.com/640x360?text=Live+Stream';
            videoTitle.textContent = data.title;
            videoChannel.textContent = (data.is_live ? '🔴 LIVE STREAM • ' : '') + data.uploader;
            videoDurationBadge.textContent = data.is_live ? 'LIVE' : data.duration;
            videoDurationBadge.style.background = data.is_live ? '#ef4444' : 'rgba(0,0,0,0.85)';

            previewCard.style.display = 'block';
            previewCard.scrollIntoView({ behavior: 'smooth' });

            // Auto-fill creator tag placeholder
            if (aiCreatorTag) {
                const cleanName = data.uploader ? data.uploader.replace(/[^a-zA-Z0-9_]/g, '') : 'Creator';
                aiCreatorTag.placeholder = `@${cleanName}`;
            }

        } catch (err) {
            alert('Server error: ' + err.message);
        } finally {
            fetchSpinner.style.display = 'none';
            fetchBtn.disabled = false;
        }
    }

    // 4. Start AI 9:16 Shorts Generation
    startAiBtn.addEventListener('click', async () => {
        if (!currentVideoInfo) return;

        const payload = {
            url: videoUrlInput.value.trim(),
            num_clips: parseInt(aiNumClips.value),
            clip_duration: parseInt(aiClipDuration.value),
            hook_style: aiHookStyle.value,
            quality: aiShortQuality ? aiShortQuality.value : '1080p',
            frame_style: aiFrameStyle ? aiFrameStyle.value : 'blur_bg',
            enable_overlay: aiEnableOverlay ? aiEnableOverlay.checked : true,
            overlay_badge: aiOverlayBadge && aiOverlayBadge.value.trim() ? aiOverlayBadge.value.trim() : 'GTA VI',
            creator_tag: aiCreatorTag && aiCreatorTag.value.trim() ? aiCreatorTag.value.trim() : null,
        };

        startAiBtn.disabled = true;
        startAiBtn.textContent = '⏳ AI Scanner Running...';
        aiShortsCard.style.display = 'none';
        completeCard.style.display = 'none';

        try {
            const res = await fetch('/api/ai-shorts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (data.job_id) {
                progressCard.style.display = 'flex';
                progressCard.scrollIntoView({ behavior: 'smooth' });
                pollAiShortsProgress(data.job_id);
            } else {
                alert('AI Shorts job start nahi ho payi.');
                startAiBtn.disabled = false;
                startAiBtn.textContent = '⚡ Generate AI 9:16 Shorts Now';
            }
        } catch (err) {
            alert('Server error: ' + err.message);
            startAiBtn.disabled = false;
            startAiBtn.textContent = '⚡ Generate AI 9:16 Shorts Now';
        }
    });

    // 5. Poll AI Shorts Progress
    function pollAiShortsProgress(jobId) {
        if (pollInterval) clearInterval(pollInterval);

        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/ai-shorts/progress/${jobId}`);
                if (!res.ok) return;

                const job = await res.json();

                downloadStatusText.textContent = job.stage || 'Processing AI Shorts...';
                progressPercent.textContent = `${job.percent}%`;
                progressBarFill.style.width = `${job.percent}%`;
                downloadSpeed.textContent = job.speed ? `Speed: ${job.speed}` : `Status: ${job.status.toUpperCase()}`;
                downloadEta.textContent = job.eta ? `Time: ${job.eta}` : (job.percent < 50 ? 'Downloading & Scanning...' : 'Cutting 9:16 clips with hooks...');

                if (job.status === 'completed') {
                    clearInterval(pollInterval);
                    showAiShortsResults(job);
                } else if (job.status === 'error') {
                    clearInterval(pollInterval);
                    alert('AI Clipping Error:\n' + (job.error || 'Unknown error'));
                    progressCard.style.display = 'none';
                    startAiBtn.disabled = false;
                    startAiBtn.textContent = '⚡ Generate AI 9:16 Shorts Now';
                }
            } catch (err) {
                console.error('Polling error', err);
            }
        }, 1000);
    }

    // 6. Show AI Generated 9:16 Shorts
    function showAiShortsResults(job) {
        progressCard.style.display = 'none';
        startAiBtn.disabled = false;
        startAiBtn.textContent = '⚡ Generate AI 9:16 Shorts Now';

        aiResultsSubtitle.textContent = `${job.clips.length} high-energy 9:16 vertical shorts generated from "${job.video_title || 'Stream'}"`;
        downloadAllZipBtn.href = job.zip_url || '#';

        shortsGrid.innerHTML = '';

        job.clips.forEach(clip => {
            const card = document.createElement('div');
            card.className = 'short-card';
            card.innerHTML = `
                <div class="short-video-wrapper">
                    <video controls preload="metadata" poster="${clip.thumb_url}" playsinline webkit-playsinline>
                        <source src="${clip.media_url}" type="video/mp4">
                    </video>
                    <div class="short-badge-row">
                        <span class="short-badge">⏱ ${clip.duration}s</span>
                        <span class="short-badge score">🔥 ${clip.score}</span>
                    </div>
                </div>
                <div class="short-info">
                    <div class="short-title">${clip.title}</div>
                    <div class="short-meta">
                        <span>Range: ${clip.time_range}</span>
                        <span>9:16 Vertical</span>
                    </div>
                    <a href="${clip.download_url}" class="btn-short-download" download="${clip.filename}">
                        ⬇ Download 9:16 MP4
                    </a>
                </div>
            `;
            shortsGrid.appendChild(card);
        });

        aiShortsCard.style.display = 'flex';
        aiShortsCard.scrollIntoView({ behavior: 'smooth' });
        loadDownloadsHistory();
    }

    // 7. Full Video Download
    startDownloadBtn.addEventListener('click', async () => {
        if (!currentVideoInfo) return;

        const isAudioOnly = (selectedQuality === "audio_only");
        const payload = {
            url: videoUrlInput.value.trim(),
            quality: isAudioOnly ? "720p" : selectedQuality,
            format_type: isAudioOnly ? "mp3" : "mp4",
        };

        startDownloadBtn.disabled = true;
        startDownloadBtn.textContent = '⏳ Downloading Video...';

        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (data.job_id) {
                progressCard.style.display = 'flex';
                progressCard.scrollIntoView({ behavior: 'smooth' });
                pollDownloadProgress(data.job_id);
            } else {
                alert('Download start nahi ho paya.');
                startDownloadBtn.disabled = false;
                startDownloadBtn.textContent = '📥 Full Video Download Start Karein';
            }
        } catch (err) {
            alert('Server error: ' + err.message);
            startDownloadBtn.disabled = false;
            startDownloadBtn.textContent = '📥 Full Video Download Start Karein';
        }
    });

    // 8. Poll Full Download Progress
    function pollDownloadProgress(jobId) {
        if (pollInterval) clearInterval(pollInterval);

        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/progress/${jobId}`);
                if (!res.ok) return;

                const job = await res.json();

                if (job.status === 'downloading') {
                    downloadStatusText.textContent = 'Downloading Full Stream...';
                    progressPercent.textContent = `${job.percent}%`;
                    progressBarFill.style.width = `${job.percent}%`;
                    downloadSpeed.textContent = `Speed: ${job.speed || '0 KB/s'}`;
                    downloadEta.textContent = `ETA: ${job.eta || 'calculating'}`;
                } else if (job.status === 'processing') {
                    downloadStatusText.textContent = 'Merging video and audio...';
                    progressBarFill.style.width = '99%';
                    progressPercent.textContent = '99%';
                } else if (job.status === 'completed') {
                    clearInterval(pollInterval);
                    showDownloadComplete(job);
                } else if (job.status === 'error') {
                    clearInterval(pollInterval);
                    alert('Download Fail Ho Gaya:\n' + (job.error || 'Unknown error'));
                    progressCard.style.display = 'none';
                    startDownloadBtn.disabled = false;
                    startDownloadBtn.textContent = '📥 Full Video Download Start Karein';
                }
            } catch (err) {
                console.error('Polling error', err);
            }
        }, 800);
    }

    function showDownloadComplete(job) {
        progressCard.style.display = 'none';
        startDownloadBtn.disabled = false;
        startDownloadBtn.textContent = '📥 Full Video Download Start Karein';

        downloadedFileName.textContent = job.filename || 'Downloaded_Stream.mp4';
        const fileUrl = `/media/${job.filename}`;
        const directUrl = `/download/${job.filename}`;

        videoPlayer.src = fileUrl;
        directDownloadLink.href = directUrl;
        directDownloadLink.setAttribute('download', job.filename);

        completeCard.style.display = 'flex';
        completeCard.scrollIntoView({ behavior: 'smooth' });
        loadDownloadsHistory();
    }

    downloadAnotherBtn.addEventListener('click', () => {
        completeCard.style.display = 'none';
        aiShortsCard.style.display = 'none';
        previewCard.style.display = 'none';
        videoUrlInput.value = '';
        videoUrlInput.focus();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // 9. Downloads History
    async function loadDownloadsHistory() {
        try {
            const res = await fetch('/api/downloads');
            const data = await res.json();

            downloadsList.innerHTML = '';

            if (!data.files || data.files.length === 0) {
                downloadsList.innerHTML = '<p class="empty-state">Abhi tak koi video download nahi hui.</p>';
                return;
            }

            data.files.forEach(file => {
                const item = document.createElement('div');
                item.className = 'download-item';
                item.innerHTML = `
                    <div class="item-left">
                        <span style="font-size: 1.3rem;">${file.is_video ? '🎬' : '🎵'}</span>
                        <div>
                            <div class="item-name" title="${file.filename}">${file.filename}</div>
                            <div class="item-size">${file.size_mb} MB</div>
                        </div>
                    </div>
                    <div class="item-actions">
                        <a href="${file.download_url}" class="btn-download-sm" download>⬇ Download</a>
                        <button class="btn-delete-sm" data-filename="${file.filename}" title="Delete">🗑</button>
                    </div>
                `;

                item.querySelector('.btn-delete-sm').addEventListener('click', async (e) => {
                    const fn = e.target.getAttribute('data-filename');
                    if (confirm(`Kya aap "${fn}" ko delete karna chahte hain?`)) {
                        await fetch(`/api/delete/${encodeURIComponent(fn)}`, { method: 'DELETE' });
                        loadDownloadsHistory();
                    }
                });

                downloadsList.appendChild(item);
            });

        } catch (err) {
            console.error('History fetch error', err);
        }
    }

    refreshHistoryBtn.addEventListener('click', loadDownloadsHistory);
    loadDownloadsHistory();
});

document.addEventListener("DOMContentLoaded", function () {
    const CONFIG = {
        SERVER_URL: "http://localhost:8000",
        POLL_INTERVALS: {
            initial: 2000,
            normal: 5000,
        },
        MAX_RETRIES: 3,
        STORAGE_CLEANUP_DAYS: 7,
    };

    const elements = {
        contentSection: document.getElementById("content-section"),
        videoContent: document.getElementById("video-content"),
        videoTitleEl: document.getElementById("video-title"),
        videoThumbnail: document.getElementById("video-thumbnail"),
        videoDownloadBtn: document.getElementById("video-download-btn"),
        videoResolutionSelect: document.getElementById("video-resolution"),
        audioContent: document.getElementById("audio-content"),
        audioTitleEl: document.getElementById("audio-title"),
        audioThumbnail: document.getElementById("audio-thumbnail"),
        audioDownloadBtn: document.getElementById("audio-download-btn"),
        audioQualitySelect: document.getElementById("audio-quality"),
        downloadsList: document.getElementById("downloads-list"),
        errorMessage: document.getElementById("error-message"),
        loadingIndicator: document.getElementById("loading-indicator"),
        noVideoMessage: document.getElementById("no-video-message"),
        tabButtons: document.querySelectorAll(".tab-button"),
        tabContents: document.querySelectorAll(".tab-content"),
    };

    class PopupManager {
        constructor() {
            this.statusPollInterval = null;
            this.lastDownloadsDataString = null;
            this.currentTabId = null;
            this.currentVideoId = null;
            this.isLoadingStatus = false;
            this.activeTab = 'video';
            this.videoInfo = null;
            this.isLoadingVideoInfo = false;
            this.init();
        }

        async init() {
            this.setupTabs();
            await this.setupTabInterface();
            await this.requestAndUpdateStatus(true);
            this.startStatusPolling();
        }

        setupTabs() {
            elements.tabButtons.forEach(button => {
                button.addEventListener('click', () => {
                    const tabName = button.dataset.tab;
                    this.switchTab(tabName);
                });
            });
        }

        switchTab(tabName) {
            this.activeTab = tabName;
            elements.tabButtons.forEach(button => {
                button.classList.toggle('active', button.dataset.tab === tabName);
            });
            elements.tabContents.forEach(content => {
                content.classList.toggle('active', content.id === `${tabName}-tab`);
            });
        }

        async getCachedVideoInfo(videoId) {
            try {
                const cacheKey = `videoInfo_${videoId}`;
                const result = await chrome.storage.session.get(cacheKey);
                if (result && result[cacheKey]) {
                    const cachedItem = result[cacheKey];
                    const cacheTime = cachedItem.timestamp || 0;
                    if (Date.now() - cacheTime < 3600000) { // 1 hour validity
                        return cachedItem.data;
                    } else {
                        await chrome.storage.session.remove(cacheKey);
                    }
                }
            } catch (e) {
                console.warn("Error reading from session storage cache:", e);
            }
            return null;
        }

        async setCachedVideoInfo(videoId, data) {
            try {
                const cacheKey = `videoInfo_${videoId}`;
                const itemToCache = {
                    timestamp: Date.now(),
                    data: data
                };
                await chrome.storage.session.set({ [cacheKey]: itemToCache });
            } catch (e) {
                console.warn("Error writing to session storage cache:", e);
            }
        }

        // Inside PopupManager class in popup.js

        // In popup.js, update the loadVideoInfo method:

        async loadVideoInfo(videoId) {
            const cachedData = await this.getCachedVideoInfo(videoId);
            if (cachedData) {
                this.videoInfo = cachedData;
                this.updateQualityOptions();
                return;
            }

            if (this.isLoadingVideoInfo) return;
            
            this.isLoadingVideoInfo = true;
            this.showLoadingInDropdowns();

            try {
                // Ultra-aggressive timeouts - up to 5 minutes for very long videos
                let timeoutDuration = 120000; // 2 minutes initial (up from 30s)
                let attempt = 1;
                const maxAttempts = 2; 

                while (attempt <= maxAttempts) {
                    try {
                        const controller = new AbortController();
                        const timeoutId = setTimeout(() => {
                            console.warn(`VID_INFO_FRONTEND: Aborting fetch for attempt ${attempt} due to timeout (${timeoutDuration}ms) for video ${videoId}`);
                            controller.abort();
                        }, timeoutDuration);

                        console.log(`VID_INFO_FRONTEND: Attempt ${attempt} to fetch video info for ${videoId} with timeout ${timeoutDuration}ms`);
                        const response = await fetch(`${CONFIG.SERVER_URL}/api/video_info/${videoId}`, {
                            signal: controller.signal
                        });
                        
                        clearTimeout(timeoutId); 
                        
                        console.log(`VID_INFO_FRONTEND: Attempt ${attempt} for ${videoId} - Response status: ${response.status}`);
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status} ${response.statusText}`);
                        }
                        
                        const data = await response.json();
                        console.log(`VID_INFO_FRONTEND: Attempt ${attempt} for ${videoId} - Data received, success: ${data.success}`);
                        if (data.success) {
                            this.videoInfo = data;
                            await this.setCachedVideoInfo(videoId, data);
                            this.updateQualityOptions();
                            this.isLoadingVideoInfo = false; 
                            return; 
                        } else {
                            throw new Error(data.message || 'Server returned non-success for video info');
                        }
                    } catch (error) {
                        console.warn(`VID_INFO_FRONTEND: Attempt ${attempt} for ${videoId} - Error:`, error.name, error.message);
                        if (error.name === 'AbortError' && attempt < maxAttempts) {
                            console.log(`VID_INFO_FRONTEND: Video info request timed out on attempt ${attempt} for ${videoId} (${timeoutDuration}ms), retrying...`);
                            timeoutDuration = 300000; // 5 minutes for retry (ultra-aggressive)
                            attempt++;
                            this.showRetryingInDropdowns(); 
                            continue; 
                        } else {
                            throw error; 
                        }
                    }
                }
            } catch (error) { 
                console.error(`VID_INFO_FRONTEND: Final error for ${videoId} after all attempts or non-timeout error:`, error.name, error.message);
                if (error.name === 'AbortError') {
                    this.showTimeoutInDropdowns();
                } else {
                    this.showErrorInDropdowns();
                }
            } finally {
                if(this.isLoadingVideoInfo) { 
                    this.isLoadingVideoInfo = false;
                }
            }
        }

        showLoadingInDropdowns() {
            const videoSelect = elements.videoResolutionSelect;
            videoSelect.innerHTML = `
                <option value="360">360p (Loading...)</option>
                <option value="480">480p (Loading...)</option>
                <option value="720" selected>720p (HD) (Loading...)</option>
                <option value="1080">1080p (Full HD) (Loading...)</option>
            `;
            const audioSelect = elements.audioQualitySelect;
            audioSelect.innerHTML = `
                <option value="128" selected>128 kbps (Standard) (Loading...)</option>
                <option value="192">192 kbps (High) (Loading...)</option>
                <option value="256">256 kbps (Very High) (Loading...)</option>
                <option value="320">320 kbps (Premium) (Loading...)</option>
            `;
        }

        showRetryingInDropdowns() {
            const videoSelect = elements.videoResolutionSelect;
            videoSelect.innerHTML = `
                <option value="360">360p (Retrying...)</option>
                <option value="480">480p (Retrying...)</option>
                <option value="720" selected>720p (HD) (Retrying...)</option>
                <option value="1080">1080p (Full HD) (Retrying...)</option>
            `;
            const audioSelect = elements.audioQualitySelect;
            audioSelect.innerHTML = `
                <option value="128" selected>128 kbps (Standard) (Retrying...)</option>
                <option value="192">192 kbps (High) (Retrying...)</option>
                <option value="256">256 kbps (Very High) (Retrying...)</option>
                <option value="320">320 kbps (Premium) (Retrying...)</option>
            `;
        }

        showErrorInDropdowns() {
            const videoSelect = elements.videoResolutionSelect;
            videoSelect.innerHTML = `
                <option value="360">360p (Size unavailable)</option>
                <option value="480">480p (Size unavailable)</option>
                <option value="720" selected>720p (HD) (Size unavailable)</option>
                <option value="1080">1080p (Full HD) (Size unavailable)</option>
            `;
            const audioSelect = elements.audioQualitySelect;
            audioSelect.innerHTML = `
                <option value="128" selected>128 kbps (Standard) (Size unavailable)</option>
                <option value="192">192 kbps (High) (Size unavailable)</option>
                <option value="256">256 kbps (Very High) (Size unavailable)</option>
                <option value="320">320 kbps (Premium) (Size unavailable)</option>
            `;
        }

        showTimeoutInDropdowns() {
            const videoSelect = elements.videoResolutionSelect;
            videoSelect.innerHTML = `
                <option value="360">360p (Timeout)</option>
                <option value="480">480p (Timeout)</option>
                <option value="720" selected>720p (HD) (Timeout)</option>
                <option value="1080">1080p (Full HD) (Timeout)</option>
            `;
            const audioSelect = elements.audioQualitySelect;
            audioSelect.innerHTML = `
                <option value="128" selected>128 kbps (Standard) (Timeout)</option>
                <option value="192">192 kbps (High) (Timeout)</option>
                <option value="256">256 kbps (Very High) (Timeout)</option>
                <option value="320">320 kbps (Premium) (Timeout)</option>
            `;
        }

        updateQualityOptions() {
            if (!this.videoInfo) return;
        
            const videoSelect = elements.videoResolutionSelect;
            const currentVideoValue = videoSelect.value;
            videoSelect.innerHTML = '';
            
            const videoQualities = [
                { value: '360', label: '360p' },
                { value: '480', label: '480p' },
                { value: '720', label: '720p (HD)' },
                { value: '1080', label: '1080p (Full HD)' }
            ];
            
            videoQualities.forEach(quality => {
                const option = document.createElement('option');
                option.value = quality.value;
                const formatInfo = this.videoInfo.video_formats[quality.value];
                let sizeText = '';
                
                if (formatInfo && formatInfo.filesize) {
                    const sizeMB = (formatInfo.filesize / (1024 * 1024)).toFixed(1);
                    const prefix = formatInfo.estimated ? '~' : '';
                    sizeText = ` (${prefix}${sizeMB}MB)`;
                }
                
                option.textContent = quality.label + sizeText;
                if (quality.value === currentVideoValue) option.selected = true;
                videoSelect.appendChild(option);
            });

            const audioSelect = elements.audioQualitySelect;
            const currentAudioValue = audioSelect.value;
            audioSelect.innerHTML = '';
            const audioQualities = [
                { value: '128', label: '128 kbps (Standard)' },
                { value: '192', label: '192 kbps (High)' },
                { value: '256', label: '256 kbps (Very High)' },
                { value: '320', label: '320 kbps (Premium)' }
            ];
            audioQualities.forEach(quality => {
                const option = document.createElement('option');
                option.value = quality.value;
                const formatInfo = this.videoInfo.audio_formats[quality.value];
                let sizeText = '';
                if (formatInfo && formatInfo.filesize) {
                    const sizeMB = (formatInfo.filesize / (1024 * 1024)).toFixed(1);
                    const estimatedPrefix = formatInfo.estimated ? '~' : '';
                    sizeText = ` (${estimatedPrefix}${sizeMB}MB)`;
                }
                option.textContent = quality.label + sizeText;
                if (quality.value === currentAudioValue) option.selected = true;
                audioSelect.appendChild(option);
            });
        }

        resetQualityOptions() {
            const videoSelect = elements.videoResolutionSelect;
            videoSelect.innerHTML = `
                <option value="360">360p</option>
                <option value="480">480p</option>
                <option value="720" selected>720p (HD)</option>
                <option value="1080">1080p (Full HD)</option>
            `;
            const audioSelect = elements.audioQualitySelect;
            audioSelect.innerHTML = `
                <option value="128" selected>128 kbps (Standard)</option>
                <option value="192">192 kbps (High)</option>
                <option value="256">256 kbps (Very High)</option>
                <option value="320">320 kbps (Premium)</option>
            `;
        }

        async setupTabInterface() {
            try {
                const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
                if (!tabs || tabs.length === 0 || !tabs[0].url) {
                    this.showNoVideoMessage();
                    this.currentTabId = tabs[0]?.id;
                    this.currentVideoId = null;
                    this.videoInfo = null;
                    this.resetQualityOptions();
                    return;
                }

                const currentTab = tabs[0];
                this.currentTabId = currentTab.id;

                if (this.isYouTubeVideo(currentTab.url)) {
                    const videoId = this.extractVideoId(currentTab.url);
                    if (videoId !== this.currentVideoId) {
                        this.currentVideoId = videoId;
                        this.videoInfo = null; 
                        this.setupYouTubeInterface(currentTab, videoId);
                    }
                    elements.contentSection.style.display = "block";
                    elements.noVideoMessage.style.display = "none";
                } else {
                    this.currentVideoId = null;
                    this.videoInfo = null;
                    this.resetQualityOptions();
                    this.showNoVideoMessage();
                }
            } catch (error) {
                this.showError("Error setting up tab interface. Check console.");
                this.showNoVideoMessage();
                this.currentVideoId = null;
                this.videoInfo = null;
                this.resetQualityOptions();
            }
        }

        isYouTubeVideo(url) {
            return url && /youtube\.com\/watch\?v=/.test(url);
        }

        setupYouTubeInterface(tab, videoId) {
            elements.videoContent.style.display = "block";
            elements.audioContent.style.display = "block";
            this.clearMessage();

            const title = this.extractTitle(tab.title);
            const thumbnailUrl = `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`;

            elements.videoTitleEl.textContent = title || `Video ID: ${videoId}`;
            elements.videoThumbnail.src = thumbnailUrl;
            elements.videoDownloadBtn.onclick = () => this.handleDownload(videoId, title, 'video');

            elements.audioTitleEl.textContent = title || `Video ID: ${videoId}`;
            elements.audioThumbnail.src = thumbnailUrl;
            elements.audioDownloadBtn.onclick = () => this.handleDownload(videoId, title, 'audio');
            
            this.resetQualityOptions(); 
            this.loadVideoInfo(videoId);
        }

        extractVideoId(url) {
            const match = url.match(/[?&]v=([^&]+)/);
            return match ? match[1] : "";
        }

        extractTitle(title) {
            return title ? title.replace(/ - YouTube$/i, "").trim() : "";
        }

        showNoVideoMessage() {
            elements.contentSection.style.display = "none";
            elements.noVideoMessage.style.display = "block";
            this.clearMessage();
        }

        async handleDownload(videoId, title, type) {
            if (!this.validateInputs(videoId)) return;

            const downloadBtn = type === 'video' ? elements.videoDownloadBtn : elements.audioDownloadBtn;
            const originalText = 'Download';
            
            this.setDownloadButtonState(downloadBtn, true, "Sending...");
            this.clearMessage();

            try {
                await this.requestAndUpdateStatus(true);
                const response = await this.sendDownloadRequest(videoId, title, type);
                this.handleDownloadResponse(response);
            } catch (error) {
                this.showError(`Error: ${error.message}`);
                this.toggleLoadingIndicator(false);
            } finally {
                this.setDownloadButtonState(downloadBtn, false, originalText);
            }
        }

        validateInputs(videoId) {
            if (!videoId) {
                this.showError("Invalid YouTube video URL");
                return false;
            }
            return true;
        }

        sendDownloadRequest(videoId, title, type) {
            const endpoint = type === 'audio' ? 'download_audio' : 'download_video';
            const data = { videoId, title: title || `youtube_${videoId}` };
            if (type === 'video') data.resolution = elements.videoResolutionSelect.value;
            else data.quality = elements.audioQualitySelect.value;

            return new Promise((resolve, reject) => {
                chrome.runtime.sendMessage({ action: "startDownload", endpoint, data },
                    (response) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(response);
                    }
                );
            });
        }

        handleDownloadResponse(response) {
            if (response?.success) {
                this.showSuccess(`Request sent (ID: ${response.requestId.substring(0, 6)}...). Status below.`);
                this.lastDownloadsDataString = null;
                this.requestAndUpdateStatus(true);
            } else {
                this.showError(response?.message || "Could not start download");
                this.toggleLoadingIndicator(false);
            }
        }

        setDownloadButtonState(button, disabled, text) {
            button.disabled = disabled;
            button.textContent = text;
        }

        showMessage(message, type) {
            elements.errorMessage.textContent = message;
            elements.errorMessage.className = `message-area visible ${type}`;
        }

        showError(message) { this.showMessage(message, "error"); }
        showSuccess(message) { this.showMessage(message, "success"); }
        clearMessage() {
            elements.errorMessage.textContent = "";
            elements.errorMessage.className = "message-area";
        }

        toggleLoadingIndicator(show) {
            if (elements.loadingIndicator) {
                elements.loadingIndicator.classList.toggle("visible", show);
            }
            this.isLoadingStatus = show;
        }

        async requestAndUpdateStatus(showLoader = false) {
            if (showLoader && !this.isLoadingStatus) this.toggleLoadingIndicator(true);

            return new Promise((resolve) => {
                chrome.runtime.sendMessage({ action: "getStatus" }, (response) => {
                    if (showLoader || this.isLoadingStatus) this.toggleLoadingIndicator(false);

                    if (chrome.runtime.lastError) {
                        elements.downloadsList.innerHTML = '<li class="no-downloads"><span class="status-text">Error retrieving status.</span></li>';
                        this.lastDownloadsDataString = null;
                        resolve();
                        return;
                    }

                    if (response?.success) {
                        const currentDownloadsDataString = JSON.stringify(response.downloads);
                        if (currentDownloadsDataString === this.lastDownloadsDataString) {
                            resolve();
                            return;
                        }
                        this.lastDownloadsDataString = currentDownloadsDataString;
                        this.displayDownloads(response.downloads);
                    } else {
                        elements.downloadsList.innerHTML = '<li class="no-downloads"><span class="status-text">Could not retrieve download status.</span></li>';
                        this.lastDownloadsDataString = null;
                    }
                    resolve();
                });
            });
        }

        displayDownloads(downloads) {
            elements.downloadsList.innerHTML = "";
            if (Object.keys(downloads).length === 0) {
                elements.downloadsList.innerHTML = '<li class="no-downloads"><span class="status-text">No active or recent downloads.</span></li>';
                return;
            }
            const sortedEntries = Object.entries(downloads).sort(([, a], [, b]) => (b.timestamp || 0) - (a.timestamp || 0));
            sortedEntries.forEach(([requestId, download]) => {
                const li = this.createDownloadItem(requestId, download);
                elements.downloadsList.appendChild(li);
            });
        }

        createDownloadItem(requestId, download) {
            const li = document.createElement("li");
            li.dataset.requestId = requestId;
            const statusSpan = document.createElement("span");
            statusSpan.classList.add("status-text");
            const sizeInfo = this.getFileSizeInfo(download);
            const displayId = requestId.substring(0, 6);
            const title = download.title || "Unknown Content";
            const type = download.type || "video";
            const typeIcon = type === 'audio' ? '🎵' : '🎥';
            const status = download.status || "Unknown";
            const message = download.message ? `<span class="message-detail">${download.message}</span>` : "";
            statusSpan.innerHTML = `<b>${typeIcon} ${title} (${displayId}...)</b><i data-status="${status}">${status}</i>${sizeInfo}${message}`;
            li.appendChild(statusSpan);
            const actionsDiv = this.createActionButtons(requestId, download);
            li.appendChild(actionsDiv);
            return li;
        }

        getFileSizeInfo(download) {
            if (download.file_size_mb && ["complete", "failed"].includes(download.status)) {
                return ` <span class="size-info">- Size: ${download.file_size_mb.toFixed(1)}MB</span>`;
            }
            return "";
        }

        createActionButtons(requestId, download) {
            const actionsDiv = document.createElement("div");
            actionsDiv.classList.add("action-buttons");
            if (download.status === "complete" && download.download_url) {
                const link = document.createElement("a");
                link.href = download.download_url;
                link.textContent = "Save File";
                link.target = "_blank";
                actionsDiv.appendChild(link);
            }
            if (["complete", "failed", "not_found", "error"].includes(download.status)) {
                const clearButton = this.createClearButton(requestId);
                actionsDiv.appendChild(clearButton);
            }
            return actionsDiv;
        }

        createClearButton(requestId) {
            const clearButton = document.createElement("button");
            clearButton.textContent = "Clear";
            clearButton.onclick = (e) => {
                e.stopPropagation();
                this.clearDownload(requestId, clearButton);
            };
            return clearButton;
        }

        async clearDownload(requestId, button) {
            button.disabled = true;
            button.textContent = "Clearing...";
            await this.requestAndUpdateStatus(true);
            chrome.runtime.sendMessage({ action: "clearDownload", data: { requestId } },
                (response) => {
                    if (chrome.runtime.lastError) {
                        alert(`Failed to clear: ${chrome.runtime.lastError.message}`);
                        button.disabled = false;
                        button.textContent = "Clear";
                        this.toggleLoadingIndicator(false);
                        return;
                    }
                    if (response?.success) {
                        this.lastDownloadsDataString = null;
                        this.requestAndUpdateStatus(true);
                    } else {
                        alert(`Failed to clear entry: ${response?.message || "Unknown error"}`);
                        button.disabled = false;
                        button.textContent = "Clear";
                        this.toggleLoadingIndicator(false);
                    }
                }
            );
        }

        startStatusPolling() {
            this.stopStatusPolling();
            this.statusPollInterval = setInterval(async () => {
                if (document.body && document.body.isConnected) {
                    await this.requestAndUpdateStatus(false);
                } else {
                    this.stopStatusPolling();
                }
            }, 5000);
            window.addEventListener('unload', () => this.stopStatusPolling(), { once: true });
        }

        stopStatusPolling() {
            if (this.statusPollInterval) {
                clearInterval(this.statusPollInterval);
                this.statusPollInterval = null;
            }
        }
    }

    new PopupManager();
});

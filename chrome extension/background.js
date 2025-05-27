const CONFIG = {
     SERVER_URL: "http://localhost:8000",
     POLL_INTERVALS: {
         initial: 2000,
         normal: 5000,
         slow: 10000,
     },
     MAX_RETRIES: 3,
     STORAGE_CLEANUP_DAYS: 7,
     FILE_IO_UPLOAD: false,
 };
 
 class DownloadManager {
     constructor() {
         this.activeDownloads = {};
         this.init();
     }
 
     async init() {
         await this.loadDownloads();
         await this.cleanupOldDownloads();
         this.restartPolling();
     }
 
     async loadDownloads() {
         try {
             const result = await chrome.storage.local.get("activeDownloads");
             this.activeDownloads = result.activeDownloads || {};
         } catch (error) {
             this.activeDownloads = {};
         }
     }
 
     async saveDownloads() {
         try {
             await chrome.storage.local.set({ activeDownloads: this.activeDownloads });
         } catch (error) {
             console.error("Error saving downloads:", error);
         }
     }
 
     async cleanupOldDownloads() {
         const cutoff = Date.now() - CONFIG.STORAGE_CLEANUP_DAYS * 24 * 60 * 60 * 1000;
         let hasChanges = false;
         for (const [requestId, download] of Object.entries(this.activeDownloads)) {
             if (download.timestamp && download.timestamp < cutoff) {
                 this.stopPolling(requestId);
                 delete this.activeDownloads[requestId];
                 hasChanges = true;
             }
         }
         if (hasChanges) {
             await this.saveDownloads();
         }
     }
 
     restartPolling() {
         Object.entries(this.activeDownloads).forEach(([requestId, download]) => {
             if (["pending", "processing", "uploading"].includes(download.status)) {
                 this.startPolling(requestId, download.title);
             }
         });
     }
 
     async startDownload(endpoint, videoId, data) {
         try {
             const response = await fetch(`${CONFIG.SERVER_URL}/api/${endpoint}`, {
                 method: "POST",
                 headers: { "Content-Type": "application/json" },
                 body: JSON.stringify(data),
             });
 
             if (!response.ok) {
                 const errorData = await response.json().catch(() => ({}));
                 throw new Error(
                     `HTTP ${response.status}: ${errorData.message || "Server error"}`
                 );
             }
             const responseData = await response.json();
             if (responseData.success) {
                 this.startPolling(responseData.requestId, data.title);
                 return { success: true, requestId: responseData.requestId };
             } else {
                 throw new Error(responseData.message || "Server rejected request");
             }
         } catch (error) {
             return { success: false, message: error.message };
         }
     }
 
     startPolling(requestId, title) {
         if (this.activeDownloads[requestId]?.pollingInterval) {
             return;
         }
         this.activeDownloads[requestId] = {
             status: "pending",
             message: "Request sent, waiting for server...",
             title,
             timestamp: Date.now(),
             pollingInterval: null,
             download_url: null,
             retryCount: 0,
         };
         this.pollStatus(requestId);
         const intervalId = setInterval(() => this.pollStatus(requestId), CONFIG.POLL_INTERVALS.initial);
         this.activeDownloads[requestId].pollingInterval = intervalId;
         this.saveDownloads();
     }
 
     async pollStatus(requestId) {
         const download = this.activeDownloads[requestId];
         if (!download) return;
 
         try {
             const response = await fetch(
                 `${CONFIG.SERVER_URL}/api/download_status/${requestId}`
             );
             if (!response.ok) {
                 if (response.status === 404) {
                     this.handleNotFound(requestId);
                     return;
                 }
                 throw new Error(`HTTP ${response.status}`);
             }
             const data = await response.json();
             this.updateDownloadStatus(requestId, data);
         } catch (error) {
             this.handlePollError(requestId, error);
         }
     }
 
     updateDownloadStatus(requestId, data) {
         const download = this.activeDownloads[requestId];
         if (!download) return;
 
         download.status = data.status;
         download.message = data.message;
         download.download_url = data.download_url;
         download.file_size_mb = data.file_size_mb;
         download.type = data.type; // Add type tracking
         download.retryCount = 0;
 
         if (data.status === "processing" || data.status === "uploading") {
             this.adjustPollingInterval(requestId, CONFIG.POLL_INTERVALS.normal);
         }
         if (["complete", "failed"].includes(data.status)) {
             this.stopPolling(requestId);
             this.notifyUser(requestId, data.status);
         }
         this.saveDownloads();
     }
 
     handleNotFound(requestId) {
         if (this.activeDownloads[requestId]) {
             this.activeDownloads[requestId].status = "not_found";
             this.activeDownloads[requestId].message = "Request not found on server";
             this.stopPolling(requestId);
             this.saveDownloads();
         }
     }
 
     handlePollError(requestId, error) {
         const download = this.activeDownloads[requestId];
         if (!download) return;
         download.retryCount = (download.retryCount || 0) + 1;
         if (download.retryCount >= CONFIG.MAX_RETRIES) {
             download.status = "error";
             download.message = `Polling failed: ${error.message}`;
             this.stopPolling(requestId);
         }
         this.saveDownloads();
     }
 
     adjustPollingInterval(requestId, newInterval) {
         const download = this.activeDownloads[requestId];
         if (!download?.pollingInterval) return;
         clearInterval(download.pollingInterval);
         download.pollingInterval = setInterval(() => this.pollStatus(requestId), newInterval);
     }
 
     stopPolling(requestId) {
         const download = this.activeDownloads[requestId];
         if (download?.pollingInterval) {
             clearInterval(download.pollingInterval);
             download.pollingInterval = null;
             this.saveDownloads();
         }
     }
 
     notifyUser(requestId, status) {
         const download = this.activeDownloads[requestId];
         if (!download) return;
         const title = download.title || "Content Download";
         const type = download.type || "video";
         const typeIcon = type === 'audio' ? '🎵' : '🎥';
         const message =
             status === "complete"
                 ? `${typeIcon} Download complete! Click to open link.`
                 : `${typeIcon} Download failed: ${download.message}`;
         chrome.notifications.create(requestId, {
             type: "basic",
             iconUrl: "icon48.png",
             title,
             message,
         });
     }
 
     async clearDownload(requestId) {
         const download = this.activeDownloads[requestId];
         if (download) {
             this.stopPolling(requestId);
 
             if (
                 download.status === "complete" &&
                 download.download_url &&
                 !CONFIG.FILE_IO_UPLOAD
             ) {
                 try {
                     const urlParts = download.download_url.split("/");
                     let filenameFromServer = urlParts[urlParts.length - 1];
                     let decodedFilename = filenameFromServer;
 
                     if (filenameFromServer) {
                         try {
                             decodedFilename = decodeURIComponent(filenameFromServer);
                         } catch (e) {
                             console.error("Error decoding filename component:", filenameFromServer, e);
                         }
                         
                         const deleteResponse = await fetch(
                             `${CONFIG.SERVER_URL}/api/delete_file`,
                             {
                                 method: "POST",
                                 headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify({ filename: decodedFilename }),
                             }
                         );
                         const deleteResult = await deleteResponse.json();
                         if (!deleteResult.success) {
                             console.warn(
                                 `Server failed to delete ${decodedFilename}: ${deleteResult.message}`
                             );
                         }
                     }
                 } catch (error) {
                     console.error("Error requesting file deletion from server:", error);
                 }
             }
             delete this.activeDownloads[requestId];
             await this.saveDownloads();
             return { success: true, message: "Download cleared." };
         }
         return { success: false, message: "Download not found" };
     }
 
     getStatus() {
         return { success: true, downloads: this.activeDownloads };
     }
 }
 
 const downloadManager = new DownloadManager();
 
 chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
     const handleAsync = async () => {
         switch (request.action) {
             case "startDownload":
                 return await downloadManager.startDownload(
                     request.endpoint || "download_video", // Use provided endpoint or default
                     request.data.videoId,
                     request.data
                 );
             case "getStatus":
                 return downloadManager.getStatus();
             case "clearDownload":
                 return await downloadManager.clearDownload(request.data.requestId);
             default:
                 return { success: false, message: "Unknown action" };
         }
     };
     handleAsync().then(sendResponse).catch(error => {
         sendResponse({ success: false, message: error.message || "Async error in background" });
     });
     return true;
 });
 
 chrome.notifications.onClicked.addListener((notificationId) => {
     const download = downloadManager.activeDownloads[notificationId];
     if (download?.status === "complete" && download.download_url) {
         chrome.tabs.create({ url: download.download_url });
     }
     chrome.notifications.clear(notificationId);
 });

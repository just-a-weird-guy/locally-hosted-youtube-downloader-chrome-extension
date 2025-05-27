import os
import uuid
import threading
import time
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
import yt_dlp
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

CONFIG = {
    'DOWNLOADS_DIR': '/app/downloads',
    'MAX_FILE_SIZE_MB': 50000,
    'CLEANUP_INTERVAL_HOURS': 24,
    'FILE_RETENTION_HOURS': 72,
    'FILE_IO_UPLOAD': False,
    'LOCAL_SERVER_URL': 'http://localhost:8000'
}

download_status = {}
download_lock = threading.Lock()
final_filenames_store = {}

class VideoDownloader:
    def __init__(self):
        self.downloads_dir = Path(CONFIG['DOWNLOADS_DIR'])
        self.downloads_dir.mkdir(exist_ok=True)
        self.final_filenames = final_filenames_store
        
        cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        cleanup_thread.start()

    def _cleanup_loop(self):
        while True:
            try:
                self._cleanup_old_files()
                self._cleanup_old_status()
                time.sleep(CONFIG['CLEANUP_INTERVAL_HOURS'] * 3600)
            except Exception as e:
                print(f"Cleanup error: {e}")
                time.sleep(3600)

    def _cleanup_old_files(self):
        cutoff = datetime.now() - timedelta(hours=CONFIG['FILE_RETENTION_HOURS'])
        cleaned_count = 0
        for file_path in self.downloads_dir.glob('*'):
            if file_path.is_file():
                try:
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff:
                        file_path.unlink()
                        cleaned_count += 1
                except Exception as e:
                    print(f"Error cleaning up file {file_path}: {e}")
        if cleaned_count > 0:
            print(f"Cleaned up {cleaned_count} old file(s).")

    def _cleanup_old_status(self):
        cutoff = datetime.now() - timedelta(hours=CONFIG['FILE_RETENTION_HOURS'])
        cleaned_count = 0
        with download_lock:
            to_remove = [
                request_id for request_id, status_data in download_status.items()
                if datetime.fromisoformat(status_data.get('created_at', '1970-01-01T00:00:00')) < cutoff
            ]
            for request_id in to_remove:
                download_status.pop(request_id, None)
                cleaned_count +=1
        if cleaned_count > 0:
            print(f"Cleaned up {cleaned_count} old status entries.")

    def _get_random_user_agent(self):
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
        ]
        return random.choice(user_agents)

    def _calculate_dynamic_timeouts(self, duration):
        """Calculate dynamic timeouts based on video duration"""
        base_timeout = 60  # 1 minute base
        
        # Scale timeout based on duration
        if duration <= 300:  # 5 minutes or less
            info_timeout = base_timeout
            sim_timeout = 90
        elif duration <= 900:  # 15 minutes or less
            info_timeout = base_timeout * 1.5
            sim_timeout = 120
        elif duration <= 1800:  # 30 minutes or less
            info_timeout = base_timeout * 2
            sim_timeout = 180
        elif duration <= 3600:  # 1 hour or less
            info_timeout = base_timeout * 2.5
            sim_timeout = 240
        elif duration <= 7200:  # 2 hours or less
            info_timeout = base_timeout * 3
            sim_timeout = 300
        else:  # Very long videos
            info_timeout = base_timeout * 4
            sim_timeout = 360  # 6 minutes for very long videos
        
        return int(info_timeout), int(sim_timeout)

    def _improved_estimation(self, resolution, duration):
        """Much more accurate estimation with better resolution differentiation"""
        # More realistic bitrates with better resolution differentiation
        base_bitrates = {
            360: 450,   # Slightly increased to create more separation
            480: 850,   # Bigger jump from 360p
            720: 1300,  # More realistic for 720p
            1080: 2800  # More realistic for 1080p
        }
        
        # Duration-based minimal scaling
        duration_factor = 1.0
        if duration > 1800:  # 30+ minutes
            duration_factor = 0.98
        elif duration > 3600:  # 1+ hour
            duration_factor = 0.96
        elif duration > 7200:  # 2+ hours
            duration_factor = 0.94
        
        # More realistic compression efficiency
        compression_factor = 0.90
        
        effective_bitrate = base_bitrates[resolution] * duration_factor * compression_factor
        estimated_size = (effective_bitrate * duration * 1000) / 8
        
        return {'filesize': int(estimated_size), 'estimated': True}

    def _improved_audio_estimation(self, quality, duration):
        """More accurate audio size estimation"""
        # More realistic audio efficiency factors
        efficiency_factors = {128: 0.88, 192: 0.90, 256: 0.92, 320: 0.94}
        
        duration_factor = 1.0
        if duration > 1800:  # 30+ minutes
            duration_factor = 0.98
        
        effective_bitrate = quality * efficiency_factors[quality] * duration_factor
        estimated_size = (effective_bitrate * duration * 1000) / 8
        
        return {'filesize': int(estimated_size), 'estimated': True}

    def _get_video_format_spec(self, resolution):
        """Get enhanced format specification with better resolution targeting"""
        if resolution == 480:
            # More specific 480p targeting
            return (
                f'bestvideo[height=480][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                f'bestvideo[height<=480][height>360][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                f'bestvideo[height=480][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height<=480][height>360][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height<=480][vcodec^=avc1]+bestaudio/'
                f'bestvideo[height<=480]+bestaudio/'
                f'best[height=480][ext=mp4]/'
                f'best[height<=480][height>360]'
            )
        elif resolution == 360:
            # More specific 360p targeting  
            return (
                f'bestvideo[height=360][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                f'bestvideo[height<=360][height>240][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                f'bestvideo[height=360][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height<=360][height>240][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height<=360][vcodec^=avc1]+bestaudio/'
                f'bestvideo[height<=360]+bestaudio/'
                f'best[height=360][ext=mp4]/'
                f'best[height<=360][height>240]'
            )
        else:
            # Keep original logic for 720p and 1080p
            return (
                f'bestvideo[height<={resolution}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height<={resolution}][vcodec^=avc1]+bestaudio/'
                f'bestvideo[height<={resolution}]+bestaudio/'
                f'bestvideo[height<={resolution}][ext=webm]+bestaudio[ext=opus]/'
                f'bestvideo[height<={resolution}][ext=webm]+bestaudio/'
                f'best[height<={resolution}][ext=mp4]/'
                f'best[height<={resolution}]'
            )

    def _calculate_total_filesize(self, sim_info):
        """Calculate total filesize from simulation info"""
        total_filesize = 0
        
        # Check for combined formats first (video + audio)
        requested_formats = sim_info.get('requested_formats')
        if requested_formats:
            for fmt_req in requested_formats:
                size = fmt_req.get('filesize') or fmt_req.get('filesize_approx')
                if size:
                    total_filesize += size
        else:
            # Single format
            total_filesize = sim_info.get('filesize') or sim_info.get('filesize_approx') or 0
        
        return total_filesize

    def _detect_and_handle_duplicate_sizes(self, video_formats):
        """Detect when resolutions have the same size and adjust accordingly"""
        sizes = {}
        duplicates = []
        
        # Group resolutions by file size
        for resolution, format_info in video_formats.items():
            size = format_info.get('filesize', 0)
            if size in sizes:
                sizes[size].append(resolution)
            else:
                sizes[size] = [resolution]
        
        # Find duplicates
        for size, resolutions in sizes.items():
            if len(resolutions) > 1:
                duplicates.extend(resolutions)
        
        # If 480p and 360p have the same size, apply intelligent adjustment
        if 480 in duplicates and 360 in duplicates:
            if video_formats[480]['filesize'] == video_formats[360]['filesize']:
                # Apply a small realistic difference (480p typically 10-20% larger)
                base_size = video_formats[360]['filesize']
                video_formats[480]['filesize'] = int(base_size * 1.15)  # 15% larger
                video_formats[480]['adjusted'] = True
                print(f"VID_INFO: Adjusted 480p size from {base_size} to {video_formats[480]['filesize']} (15% increase)")
        
        return video_formats

    def _aggressive_size_simulation(self, url, duration, info):
        """Ultra-aggressive simulation with very long timeouts and duplicate handling"""
        try:
            info_timeout, sim_timeout = self._calculate_dynamic_timeouts(duration)
            print(f"VID_INFO: Using dynamic timeouts - Info: {info_timeout}s, Simulation: {sim_timeout}s for {duration}s video")
            
            video_formats_out = {}
            audio_formats_out = {}

            # Ultra-aggressive simulation options
            base_sim_opts = {
                'quiet': True,
                'no_warnings': True,
                'simulate': True,
                'skip_download': True,
                'socket_timeout': sim_timeout,  # Dynamic timeout
                'http_headers': {
                    'User-Agent': self._get_random_user_agent(),
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'extract_flat': False,
                'no_check_certificate': True,
                'retries': 10,  # Increased retries
                'fragment_retries': 10,
            }

            # Try video formats with maximum persistence
            successful_video_sims = 0
            format_debug_info = {}
            
            for resolution in [720, 1080, 480, 360]:  # Start with most common
                success = False
                max_attempts = 4  # Increased attempts
                
                for attempt in range(max_attempts):
                    try:
                        format_spec = self._get_video_format_spec(resolution)
                        current_sim_opts = {**base_sim_opts, 'format': format_spec}
                        
                        # Add progressive timeout increase per attempt
                        attempt_timeout = sim_timeout + (attempt * 30)  # Add 30s per attempt
                        current_sim_opts['socket_timeout'] = attempt_timeout
                        
                        sim_start_time = time.time()
                        print(f"VID_INFO: Simulating {resolution}p (attempt {attempt + 1}/{max_attempts}, timeout: {attempt_timeout}s)...")
                        
                        with yt_dlp.YoutubeDL(current_sim_opts) as sim_ydl:
                            sim_info = sim_ydl.extract_info(url, download=False)
                        
                        total_filesize = self._calculate_total_filesize(sim_info)
                        sim_time = time.time() - sim_start_time
                        
                        # Store debug info about what format was actually selected
                        if 'requested_formats' in sim_info:
                            format_debug_info[resolution] = {
                                'video_format_id': sim_info['requested_formats'][0].get('format_id', 'unknown'),
                                'audio_format_id': sim_info['requested_formats'][1].get('format_id', 'unknown') if len(sim_info['requested_formats']) > 1 else 'none',
                                'video_height': sim_info['requested_formats'][0].get('height', 'unknown')
                            }
                        else:
                            format_debug_info[resolution] = {
                                'format_id': sim_info.get('format_id', 'unknown'),
                                'height': sim_info.get('height', 'unknown')
                            }
                        
                        if total_filesize > 0:
                            video_formats_out[resolution] = {'filesize': int(total_filesize), 'estimated': False}
                            successful_video_sims += 1
                            print(f"VID_INFO: ✓ Got actual size for {resolution}p: {total_filesize/1024/1024:.1f}MB (took {sim_time:.2f}s)")
                            print(f"VID_INFO: Format debug for {resolution}p: {format_debug_info[resolution]}")
                            success = True
                            break
                        else:
                            print(f"VID_INFO: No size returned for {resolution}p on attempt {attempt + 1}")

                    except Exception as e:
                        print(f"VID_INFO: Error simulating {resolution}p attempt {attempt + 1}: {e}")
                        if attempt < max_attempts - 1:  # Not the last attempt
                            delay = min(10 + (attempt * 5), 30)  # Progressive delay, max 30s
                            print(f"VID_INFO: Waiting {delay}s before retry...")
                            time.sleep(delay)
                            continue
                
                if not success:
                    print(f"VID_INFO: All attempts failed for {resolution}p, using improved estimation")
                    video_formats_out[resolution] = self._improved_estimation(resolution, duration)

            # Detect and handle duplicate sizes
            video_formats_out = self._detect_and_handle_duplicate_sizes(video_formats_out)

            # Try audio formats with maximum persistence
            successful_audio_sims = 0
            for quality_kbps in [128, 192, 256, 320]:
                success = False
                max_attempts = 4
                
                for attempt in range(max_attempts):
                    try:
                        format_spec = f'bestaudio[abr<={quality_kbps}]/bestaudio/best'
                        current_sim_opts = {**base_sim_opts, 'format': format_spec}
                        
                        attempt_timeout = sim_timeout + (attempt * 20)  # Smaller increments for audio
                        current_sim_opts['socket_timeout'] = attempt_timeout

                        sim_start_time = time.time()
                        print(f"VID_INFO: Simulating {quality_kbps}kbps audio (attempt {attempt + 1}/{max_attempts}, timeout: {attempt_timeout}s)...")
                        
                        with yt_dlp.YoutubeDL(current_sim_opts) as sim_ydl:
                            sim_info = sim_ydl.extract_info(url, download=False)
                        
                        filesize = sim_info.get('filesize') or sim_info.get('filesize_approx')
                        sim_time = time.time() - sim_start_time
                        
                        if filesize and filesize > 0:
                            audio_formats_out[quality_kbps] = {'filesize': int(filesize), 'estimated': False}
                            successful_audio_sims += 1
                            print(f"VID_INFO: ✓ Got actual size for {quality_kbps}kbps audio: {filesize/1024/1024:.1f}MB (took {sim_time:.2f}s)")
                            success = True
                            break
                        else:
                            print(f"VID_INFO: No size returned for {quality_kbps}kbps audio on attempt {attempt + 1}")

                    except Exception as e:
                        print(f"VID_INFO: Error simulating {quality_kbps}kbps audio attempt {attempt + 1}: {e}")
                        if attempt < max_attempts - 1:
                            delay = min(5 + (attempt * 3), 20)  # Smaller delays for audio
                            print(f"VID_INFO: Waiting {delay}s before retry...")
                            time.sleep(delay)
                            continue
                
                if not success:
                    print(f"VID_INFO: All attempts failed for {quality_kbps}kbps audio, using improved estimation")
                    audio_formats_out[quality_kbps] = self._improved_audio_estimation(quality_kbps, duration)

            # Check for any remaining duplicates and log them
            duplicate_sizes = {}
            for res, fmt in video_formats_out.items():
                size = fmt['filesize']
                if size in duplicate_sizes:
                    duplicate_sizes[size].append(res)
                else:
                    duplicate_sizes[size] = [res]
            
            for size, resolutions in duplicate_sizes.items():
                if len(resolutions) > 1:
                    print(f"VID_INFO: Warning - Multiple resolutions ({resolutions}) have same size: {size/1024/1024:.1f}MB")

            print(f"VID_INFO: Aggressive simulation completed - got {successful_video_sims}/4 video sizes and {successful_audio_sims}/4 audio sizes")
            
            return {
                'success': True,
                'title': info.get('title', 'Unknown Title'),
                'duration': duration,
                'video_formats': video_formats_out,
                'audio_formats': audio_formats_out,
                'thumbnail': info.get('thumbnail'),
                'estimated_only': False,
                'actual_sizes_count': {'video': successful_video_sims, 'audio': successful_audio_sims},
                'format_debug': format_debug_info if format_debug_info else None
            }

        except Exception as e:
            print(f"VID_INFO: Aggressive simulation completely failed: {e}")
            return None

    def get_video_info(self, video_id):
        try:
            url = f'https://www.youtube.com/watch?v={video_id}'
            
            # Start with extended timeout for initial info
            base_ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False, 
                'skip_download': True,
                'no_check_certificate': True,
                'socket_timeout': 120,  # 2 minutes for initial info
                'http_headers': {
                    'User-Agent': self._get_random_user_agent(),
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'retries': 5,
                'fragment_retries': 5,
            }
            
            print(f"VID_INFO: Getting initial info for {video_id} with extended timeout...")
            start_time = time.time()
            
            with yt_dlp.YoutubeDL(base_ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False) 
            
            duration = info.get('duration', 0)
            initial_time = time.time() - start_time
            print(f"VID_INFO: Initial info for {video_id} (duration: {duration}s) fetched in {initial_time:.2f}s")

            if not duration:
                print(f"VID_INFO: Could not determine duration for {video_id}. Using improved estimations.")
                # Use improved estimation with default 10-minute duration
                default_duration = 600
                video_formats = {res: self._improved_estimation(res, default_duration) for res in [360, 480, 720, 1080]}
                audio_formats = {qual: self._improved_audio_estimation(qual, default_duration) for qual in [128, 192, 256, 320]}
                
                return {
                    'success': True,
                    'title': info.get('title', 'Unknown Title'),
                    'duration': default_duration,
                    'video_formats': video_formats,
                    'audio_formats': audio_formats,
                    'thumbnail': info.get('thumbnail'),
                    'estimated_only': True,
                    'message': 'Could not determine duration, using improved estimation'
                }

            # No duration limit - try aggressive simulation for ALL videos
            print(f"VID_INFO: Attempting aggressive simulation for {video_id} ({duration}s duration)...")
            actual_sizes = self._aggressive_size_simulation(url, duration, info)
            
            if actual_sizes:
                total_time = time.time() - start_time
                print(f"VID_INFO: Aggressive simulation completed for {video_id} in {total_time:.2f}s total")
                actual_sizes['processing_time_seconds'] = round(total_time, 2)
                return actual_sizes
            
            # If even aggressive simulation fails, use improved estimation
            print(f"VID_INFO: Aggressive simulation failed, using improved estimation for {video_id}")
            video_formats = {res: self._improved_estimation(res, duration) for res in [360, 480, 720, 1080]}
            audio_formats = {qual: self._improved_audio_estimation(qual, duration) for qual in [128, 192, 256, 320]}
            
            fallback_result = {
                'success': True,
                'title': info.get('title', 'Unknown Title'),
                'duration': duration,
                'video_formats': video_formats,
                'audio_formats': audio_formats,
                'thumbnail': info.get('thumbnail'),
                'estimated_only': True,
                'message': 'Aggressive simulation failed, using improved estimation'
            }
            fallback_result['processing_time_seconds'] = round(time.time() - start_time, 2)
            return fallback_result

        except Exception as e_main:
            print(f"VID_INFO: Major error getting video info for {video_id}: {e_main}")
            # Fallback response with improved estimation
            video_formats = {res: self._improved_estimation(res, 600) for res in [360, 480, 720, 1080]}
            audio_formats = {qual: self._improved_audio_estimation(qual, 600) for qual in [128, 192, 256, 320]}
            
            return {
                'success': True,
                'title': f'Video {video_id}',
                'duration': 600,
                'video_formats': video_formats,
                'audio_formats': audio_formats,
                'thumbnail': None,
                'estimated_only': True,
                'message': f'Error occurred: {str(e_main)[:50]}...'
            }

    def start_audio_download(self, video_id, quality, title):
        request_id = str(uuid.uuid4())
        with download_lock:
            download_status[request_id] = {
                'status': 'pending',
                'message': 'Audio download request received',
                'created_at': datetime.now().isoformat(),
                'video_id': video_id,
                'quality': quality,
                'title': title,
                'type': 'audio',
                'download_url': None,
                'file_size_mb': None,
                'updated_at': datetime.now().isoformat(),
            }
        
        download_thread = threading.Thread(
            target=self._download_audio,
            args=(request_id, video_id, quality, title),
            daemon=True
        )
        download_thread.start()
        return request_id

    def _download_audio(self, request_id, video_id, quality, title):
        final_downloaded_file_path = None
        progress_hook_key = f"{request_id}_progress_{str(uuid.uuid4())[:8]}"

        try:
            self._update_status(request_id, 'processing', 'Initializing audio download...')

            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(" ", "_")
            safe_title = safe_title[:60]
            
            filename_template_str = f"{safe_title}_{video_id}_{quality}kbps.%(ext)s"
            output_template_path = self.downloads_dir / filename_template_str
            
            url = f'https://www.youtube.com/watch?v={video_id}'
            
            ydl_opts = {
                'format': f'bestaudio[abr<={quality}]/bestaudio/best',
                'outtmpl': str(output_template_path),
                'noplaylist': True,
                'writethumbnail': False,
                'writeinfojson': False,
                'extractaudio': True,
                'audioformat': 'mp3',
                'http_headers': {
                    'User-Agent': self._get_random_user_agent(),
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'retries': 5,
                'fragment_retries': 5,
                'socket_timeout': 60,
                'no_warnings': True,
                'ignoreerrors': False,
                'verbose': False,
                'progress_hooks': [lambda d: self._ydl_progress_hook(d, progress_hook_key)],
            }
            
            self._update_status(request_id, 'processing', 'Starting audio download with yt-dlp...')
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self._update_status(request_id, 'processing', 'Extracting audio...')
                ydl.download([url])

            final_filename_from_hook = self.final_filenames.pop(progress_hook_key, None)

            if final_filename_from_hook and Path(final_filename_from_hook).exists():
                final_downloaded_file_path = Path(final_filename_from_hook)
            else:
                expected_final_filename = f"{safe_title}_{video_id}_{quality}kbps.mp3"
                potential_file = self.downloads_dir / expected_final_filename
                if potential_file.exists() and potential_file.is_file():
                    final_downloaded_file_path = potential_file
                else:
                    glob_pattern = f"{safe_title}_{video_id}_{quality}kbps.*"
                    found_files = list(self.downloads_dir.glob(glob_pattern))
                    if found_files:
                        final_downloaded_file_path = found_files[0] 
            
            if not final_downloaded_file_path or not final_downloaded_file_path.exists():
                raise Exception("Downloaded audio file not found after yt-dlp execution.")

            file_size_mb = final_downloaded_file_path.stat().st_size / (1024 * 1024)
            if file_size_mb == 0:
                if final_downloaded_file_path.exists(): final_downloaded_file_path.unlink(missing_ok=True)
                raise Exception("Downloaded audio file is empty.")

            self._update_status(request_id, 'processing', 'Preparing local download link...')
            download_url = f"{CONFIG['LOCAL_SERVER_URL']}/download/{final_downloaded_file_path.name}"
            status_message = 'Audio download complete. File available locally.'

            self._update_status(
                request_id, 'complete', status_message,
                download_url=download_url, file_size_mb=file_size_mb
            )

        except Exception as e:
            error_msg = str(e)
            specific_msg = f"Audio download failed: {error_msg}"
            self._update_status(request_id, 'failed', specific_msg)
        finally:
            self.final_filenames.pop(progress_hook_key, None)

    def start_download(self, video_id, resolution, title):
        request_id = str(uuid.uuid4())
        with download_lock:
            download_status[request_id] = {
                'status': 'pending',
                'message': 'Download request received',
                'created_at': datetime.now().isoformat(),
                'video_id': video_id,
                'resolution': resolution,
                'title': title,
                'type': 'video',
                'download_url': None,
                'file_size_mb': None,
                'updated_at': datetime.now().isoformat(),
            }
        
        download_thread = threading.Thread(
            target=self._download_video,
            args=(request_id, video_id, resolution, title),
            daemon=True
        )
        download_thread.start()
        return request_id

    def _ydl_progress_hook(self, d, progress_hook_key):
        if d['status'] == 'finished':
            self.final_filenames[progress_hook_key] = d.get('filename') or d.get('info_dict', {}).get('_filename')
        elif d['status'] == 'error':
            print(f"yt-dlp reported an error for {progress_hook_key}: {d.get('error')}")

    def _get_ydl_options(self, output_template_path, resolution, progress_hook_key):
        format_spec = (
            f'bestvideo[height<={resolution}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
            f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/'
            f'bestvideo[height<={resolution}][vcodec^=avc1]+bestaudio/'
            f'bestvideo[height<={resolution}]+bestaudio/'
            f'bestvideo[height<={resolution}][ext=webm]+bestaudio[ext=opus]/'
            f'bestvideo[height<={resolution}][ext=webm]+bestaudio/'
            f'best[height<={resolution}][ext=mp4]/'
            f'best[height<={resolution}]'
        )
        
        return {
            'format': format_spec,
            'outtmpl': str(output_template_path),
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'writethumbnail': False,
            'writeinfojson': False,
            'http_headers': {
                'User-Agent': self._get_random_user_agent(),
                'Accept-Language': 'en-US,en;q=0.5',
            },
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 60,
            'no_warnings': True,
            'ignoreerrors': False,
            'verbose': False,
            'progress_hooks': [lambda d: self._ydl_progress_hook(d, progress_hook_key)],
        }

    def _download_video(self, request_id, video_id, resolution, title):
        final_downloaded_file_path = None
        progress_hook_key = f"{request_id}_progress_{str(uuid.uuid4())[:8]}"

        try:
            self._update_status(request_id, 'processing', 'Initializing download...')

            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(" ", "_")
            safe_title = safe_title[:60]
            
            filename_template_str = f"{safe_title}_{video_id}_{resolution}p.%(ext)s"
            output_template_path = self.downloads_dir / filename_template_str
            
            url = f'https://www.youtube.com/watch?v={video_id}'
            
            ydl_opts = self._get_ydl_options(output_template_path, resolution, progress_hook_key)
            
            self._update_status(request_id, 'processing', 'Starting download with yt-dlp...')
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self._update_status(request_id, 'processing', 'Downloading video...')
                ydl.download([url])

            final_filename_from_hook = self.final_filenames.pop(progress_hook_key, None)

            if final_filename_from_hook and Path(final_filename_from_hook).exists():
                final_downloaded_file_path = Path(final_filename_from_hook)
            else:
                expected_final_filename = f"{safe_title}_{video_id}_{resolution}p.mp4"
                potential_file = self.downloads_dir / expected_final_filename
                if potential_file.exists() and potential_file.is_file():
                    final_downloaded_file_path = potential_file
                else:
                    glob_pattern = f"{safe_title}_{video_id}_{resolution}p.*"
                    found_files = list(self.downloads_dir.glob(glob_pattern))
                    if found_files:
                        final_downloaded_file_path = found_files[0] 
            
            if not final_downloaded_file_path or not final_downloaded_file_path.exists():
                raise Exception("Downloaded file not found after yt-dlp execution.")

            file_size_mb = final_downloaded_file_path.stat().st_size / (1024 * 1024)
            if file_size_mb == 0:
                if final_downloaded_file_path.exists(): final_downloaded_file_path.unlink(missing_ok=True)
                raise Exception("Downloaded file is empty.")

            self._update_status(request_id, 'processing', 'Preparing local download link...')
            download_url = f"{CONFIG['LOCAL_SERVER_URL']}/download/{final_downloaded_file_path.name}"
            status_message = 'Download complete. File available locally.'

            self._update_status(
                request_id, 'complete', status_message,
                download_url=download_url, file_size_mb=file_size_mb
            )

        except yt_dlp.utils.DownloadError as de:
            error_msg = str(de).split('\n')[-1]
            user_message = f"Download failed (yt-dlp): {error_msg}"
            if "Unsupported URL" in str(de): user_message = "The video URL is unsupported or invalid."
            elif "Video unavailable" in str(de): user_message = "This video is unavailable."
            elif "Private video" in str(de): user_message = "This video is private."
            elif "HTTP Error 403" in str(de): user_message = "Access denied (403 Forbidden)."
            elif "HTTP Error 404" in str(de): user_message = "Video not found (404)."
            elif "HTTP Error 429" in str(de): user_message = "Too many requests (429)."
            self._update_status(request_id, 'failed', user_message)
        except Exception as e:
            error_msg = str(e)
            specific_msg = f"An unexpected error occurred: {error_msg}"
            if "File too large" in error_msg: specific_msg = error_msg
            elif "Downloaded file is empty" in error_msg: specific_msg = "Download resulted in an empty file."
            elif "Downloaded file not found" in error_msg: specific_msg = "Could not locate the video file after download process."
            self._update_status(request_id, 'failed', specific_msg)
        finally:
            self.final_filenames.pop(progress_hook_key, None)

    def _update_status(self, request_id, status, message, download_url=None, file_size_mb=None):
        with download_lock:
            if request_id and request_id in download_status:
                entry = download_status[request_id]
                entry['status'] = status
                entry['message'] = message
                entry['updated_at'] = datetime.now().isoformat()
                if download_url: entry['download_url'] = download_url
                if file_size_mb is not None: entry['file_size_mb'] = file_size_mb
                if 'type' not in entry:
                    if 'resolution' in entry: entry['type'] = 'video'
                    elif 'quality' in entry: entry['type'] = 'audio'

    def get_status(self, request_id):
        with download_lock:
            return download_status.get(request_id)

    def get_all_status(self):
        with download_lock:
            return dict(download_status)

downloader = VideoDownloader()

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/api/video_info/<video_id>', methods=['GET'])
def api_get_video_info(video_id):
    try:
        if not video_id or not video_id.replace('-', '').replace('_', '').isalnum() or len(video_id) > 15:
            return jsonify({'success': False, 'message': 'Invalid videoId format'}), 400
        
        info = downloader.get_video_info(video_id)
        return jsonify(info)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/download_video', methods=['POST'])
def api_download_video():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        
        video_id = data.get('videoId')
        resolution = data.get('resolution', '720')
        title = data.get('title', 'Unknown Video')
        
        if not video_id:
            return jsonify({'success': False, 'message': 'videoId is required'}), 400
        if not video_id.replace('-', '').replace('_', '').isalnum() or len(video_id) > 15:
            return jsonify({'success': False, 'message': 'Invalid videoId format'}), 400
        if resolution not in ['720', '1080', '480', '360']:
            return jsonify({'success': False, 'message': 'Invalid resolution'}), 400
        
        request_id = downloader.start_download(video_id, resolution, title)
        return jsonify({
            'success': True,
            'message': 'Download started',
            'requestId': request_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/download_audio', methods=['POST'])
def api_download_audio():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        
        video_id = data.get('videoId')
        quality = data.get('quality', '128')
        title = data.get('title', 'Unknown Audio')
        
        if not video_id:
            return jsonify({'success': False, 'message': 'videoId is required'}), 400
        if not video_id.replace('-', '').replace('_', '').isalnum() or len(video_id) > 15:
            return jsonify({'success': False, 'message': 'Invalid videoId format'}), 400
        if quality not in ['128', '192', '256', '320']:
            return jsonify({'success': False, 'message': 'Invalid audio quality'}), 400
        
        request_id = downloader.start_audio_download(video_id, quality, title)
        return jsonify({
            'success': True,
            'message': 'Audio download started',
            'requestId': request_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/download_status/<request_id>', methods=['GET'])
def api_get_download_status(request_id):
    try:
        status = downloader.get_status(request_id)
        if not status:
            return jsonify({'error': 'Request ID not found'}), 404
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def api_get_all_status():
    try:
        all_statuses = downloader.get_all_status()
        return jsonify({'downloads': all_statuses})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def serve_file_locally(filename):
    try:
        safe_filename = Path(filename).name 
        file_path = downloader.downloads_dir / safe_filename
        
        if not file_path.exists() or not file_path.is_file():
            return jsonify({'error': 'File not found or is not a file'}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=safe_filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete_file', methods=['POST'])
def api_delete_file():
    try:
        data = request.get_json()
        if not data or 'filename' not in data:
            return jsonify({'success': False, 'message': 'Filename not provided'}), 400

        filename_from_client = data['filename']
        filename = Path(filename_from_client).name 

        if not filename or filename == '.' or filename == '..':
            return jsonify({'success': False, 'message': 'Invalid filename component provided'}), 400

        file_path = downloader.downloads_dir / filename

        if file_path.exists() and file_path.is_file():
            try:
                file_path.unlink()
                return jsonify({'success': True, 'message': f'File {filename} deleted successfully.'})
            except Exception as e:
                return jsonify({'success': False, 'message': f'Could not delete file: {str(e)}'}), 500
        else:
            return jsonify({'success': False, 'message': 'File not found or is not a file.'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/', methods=['GET'])
def root_info():
    return jsonify({
        'service': 'YouTube Video Downloader',
        'status': 'running',
        'version': '3.0 - Ultra-Aggressive Size Estimation with Duplicate Handling',
        'config_file_io_upload': CONFIG['FILE_IO_UPLOAD'],
        'endpoints': {
            'health': '/health',
            'video_info': '/api/video_info/<video_id> (GET)',
            'download_video': '/api/download_video (POST)',
            'download_audio': '/api/download_audio (POST)',
            'status_single': '/api/download_status/<request_id> (GET)',
            'status_all': '/api/status (GET)',
            'serve_file': '/download/<filename> (GET)',
            'delete_file': '/api/delete_file (POST)'
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)

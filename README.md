# YouTube Video & Audio Downloader Extension

This Chrome extension enables downloading YouTube videos and audio directly through a locally hosted Python Flask backend. The backend, powered by `yt-dlp`, handles fetching video information and processing downloads. Users can select their preferred video resolution or audio quality within the extension's popup, initiate downloads, and monitor their progress.

<!-- Optional: Add a high-level screenshot or GIF here -->
<!-- ![Project Demo](./path/to/your/demo_image.png) -->

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Backend Server Setup](#backend-server-setup)
  - [Chrome Extension Setup](#chrome-extension-setup)
- [Usage](#usage)
- [Stopping the Server](#stopping-the-server)
- [Contributing](#contributing)
- [License](#license)

## Features

*   **Video & Audio Downloads:** Download YouTube videos in various resolutions (1080p, 720p, 480p, 360p) and audio in different bitrates (MP3 format).
*   **Local Server:** Utilizes a self-hosted Python Flask server for download processing, ensuring privacy and control.
*   **Dynamic Information:** Fetches video title, thumbnail, and available quality options with file size estimations.
*   **Download Management:** View the status of ongoing and completed downloads directly in the extension popup.
*   **File Management:** Option to clear download history and delete downloaded files from the server via the extension.
*   **Dockerized Backend:** Easy backend setup and management using Docker and Docker Compose.
*   **Simple Interface:** User-friendly popup for quick access and operation.

## Screenshots

<!-- Add screenshots of your extension in action -->

![Screenshot 2025-05-27 192816](https://github.com/user-attachments/assets/a47ac7cf-5e74-4814-991f-282565825486)


![Screenshot 2025-05-27 192953](https://github.com/user-attachments/assets/a502eb8a-edaf-4dd2-b198-c9a336029795) ![Screenshot 2025-05-27 192854](https://github.com/user-attachments/assets/4e172641-f82b-4c1e-a452-42b1c45c0dc3)






## Prerequisites

Before you begin, ensure you have the following installed:

*   [Docker](https://www.docker.com/get-started)
*   [Docker Compose](https://docs.docker.com/compose/install/) (usually included with Docker Desktop)
*   A modern web browser that supports Chrome extensions (e.g., Google Chrome, Brave, Edge).

## Installation

The installation process involves setting up the backend server and then loading the Chrome extension.

### Backend Server Setup

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/your-username/your-repository-name.git
    cd your-repository-name
    ```

2.  **Build and Run with Docker Compose:**
    Navigate to the directory containing the `docker-compose.yml` file and run:
    ```bash
    docker-compose up -d --build
    ```
    This command will build the Docker image (if it doesn't exist) and start the Flask server in detached mode. The server will be accessible at `http://localhost:8000`.

   **- *Alternatively, on Windows, you can run the `start_server.bat` script which executes `docker-compose up -d --build`.* -**

3.  **Verify Server:**
    Open your browser and go to `http://localhost:8000/health`. You should see a JSON response indicating the server is healthy. You can also visit `http://localhost:8000/` to see basic service information.

### Chrome Extension Setup

1.  **Open Chrome Extensions Page:**
    Open your Chrome-based browser and navigate to `chrome://extensions`.

2.  **Enable Developer Mode:**
    In the top right corner of the extensions page, toggle the "Developer mode" switch to ON.

3.  **Load Unpacked Extension:**
    *   Simply drag and drop the extension folder right in.
    - **or**
    *   Click the "Load unpacked" button that appears.
    *   Navigate to the directory where you cloned the repository.
    *   Select the folder that contains the `manifest.json` file for the extension (this should be the root of your cloned repository or a specific subfolder if you've structured it that way).
    *   Click "Select Folder".

5.  **Pin the Extension (Optional):**
    Click the puzzle icon (Extensions) in your Chrome toolbar and pin the "YouTube Video Downloader" extension for easy access.

## Usage

1.  **Navigate to a YouTube Video:** Open any YouTube video page (`youtube.com/watch?v=...`).
2.  **Open the Extension:** Click on the extension icon in your browser's toolbar.
3.  **Choose Download Type:** Select either the "Video" or "Audio" tab.
4.  **Select Quality:**
    *   For video, choose your desired resolution from the dropdown. File size estimates will be displayed if available.
    *   For audio, choose your desired bitrate from the dropdown.
5.  **Start Download:** Click the "Download" button.
6.  **Monitor Progress:** The "Download Status" section will show the progress of your download.
7.  **Save File:** Once complete, a "Save File" link will appear. Click it to save the downloaded file to your computer.
8.  **Clear Entry:** You can clear completed or failed download entries from the status list. This will also attempt to delete the file from the server if it was downloaded locally.

## Stopping the Server

To stop the backend server:

1.  Navigate to the directory containing the `docker-compose.yml` file in your terminal.
2.  Run:
    ```bash
    docker-compose down
    ```
    This will stop and remove the containers.

    *Alternatively, on Windows, you can run the `stop_server.bat` script.*

    To stop and remove volumes (all downloaded files):
    ```bash
    docker-compose down -v
    ```

## Contributing

Contributions are welcome! If you have suggestions for improvements or bug fixes, please feel free to:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/AmazingFeature`).
3.  Make your changes.
4.  Commit your changes (`git commit -m 'Add some AmazingFeature'`).
5.  Push to the branch (`git push origin feature/AmazingFeature`).
6.  Open a Pull Request.

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.

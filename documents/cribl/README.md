# How to Add Cribl Documentation

This directory is intended for storing Cribl documentation files (e.g., PDFs, HTML files) to make them available to the ObsAI Splunk Assistant.

## Steps to Add Documentation

1.  **Download Cribl Documentation:**
    *   Go to the [Cribl documentation website](https://docs.cribl.io/).
    *   Find the pages you want to add to the assistant's knowledge base.
    *   Save the pages as HTML files or download the PDF versions if available.

2.  **Place Files in this Directory:**
    *   Copy the downloaded `.html` or `.pdf` files into this `documents/cribl` directory.

3.  **Run the Ingestion Script:**
    *   The system is configured to automatically look for files in this directory and ingest them into the `cribl_docs_mxbai` collection.
    *   To trigger the ingestion, you can run the following command from the `docker_files` directory:
        ```bash
        bash run_ingest_org_and_local.sh
        ```
    *   This will ingest all documents from the `documents/repo` and `documents/cribl` directories.

Once the ingestion is complete, the chatbot will be able to answer questions about the Cribl documentation you have provided.

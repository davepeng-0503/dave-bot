document.addEventListener('DOMContentLoaded', () => {
    // --- STATE ---
    let currentStatus = null;
    let allFiles = [];
    let pollingInterval;

    // --- DOM ELEMENTS ---
    const views = {
        planning: document.getElementById('planning-view'),
        planReview: document.getElementById('plan-review-view'),
        userInput: document.getElementById('user-input-view'),
        generating: document.getElementById('generating-view'),
        done: document.getElementById('done-view'),
        error: document.getElementById('error-view'),
    };

    const elements = {
        // Planning
        timeline: document.getElementById('timeline'),
        planningProgress: document.getElementById('planning-progress'),
        // Plan Review
        planAndReasoning: document.getElementById('plan-and-reasoning'),
        relevantFilesList: document.getElementById('relevant-files-list'),
        filesToEditList: document.getElementById('files-to-edit-list'),
        generationOrderList: document.getElementById('generation-order-list'),
        approveBtn: document.getElementById('approve-btn'),
        rejectBtn: document.getElementById('reject-btn'),
        feedbackInput: document.getElementById('feedback-input'),
        sendFeedbackBtn: document.getElementById('send-feedback-btn'),
        contextFileInput: document.getElementById('context-file-input'),
        addContextFileBtn: document.getElementById('add-context-file-btn'),
        userContextFilesList: document.getElementById('user-context-files-list'),
        autocompleteList: document.getElementById('autocomplete-list'),
        // User Input
        userInputPrompt: document.getElementById('user-input-prompt'),
        userInputArea: document.getElementById('user-input-area'),
        sendUserInputBtn: document.getElementById('send-user-input-btn'),
        // Generating
        generationProgress: document.getElementById('generation-progress'),
        completedFilesCount: document.getElementById('completed-files-count'),
        totalFilesCount: document.getElementById('total-files-count'),
        completedFilesContainer: document.getElementById('completed-files-container'),
        pendingFilesList: document.getElementById('pending-files-list'),
        // Done
        doneMessage: document.getElementById('done-message'),
        commitMessage: document.getElementById('commit-message'),
        // Error
        errorMessage: document.getElementById('error-message'),
    };

    // --- API CALLS ---
    const sendAction = async (endpoint, data = {}) => {
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Unknown error');
            }
            // No need to poll immediately, let the regular interval handle it
        } catch (error) {
            console.error(`Error sending action to ${endpoint}:`, error);
            renderError({ error: `Failed to communicate with the server: ${error.message}` });
        }
    };

    const pollStatus = async () => {
        try {
            const response = await fetch('/status');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();
            updateUI(data);
        } catch (error) {
            console.error('Polling error:', error);
            // Stop polling on error to prevent spamming a dead server
            if (pollingInterval) {
                clearInterval(pollingInterval);
            }
            renderError({ error: 'Connection to the server was lost. Please check the console where the agent was started.' });
        }
    };

    // --- UI RENDERING ---
    const showView = (viewName) => {
        Object.values(views).forEach(view => view.classList.add('hidden'));
        if (views[viewName]) {
            views[viewName].classList.remove('hidden');
        }
    };

    const renderDiff = (diffText) => {
        if (!diffText) return '';
        return diffText.split('\n').map(line => {
            const lineClass = line.startsWith('+') ? 'diff-add' :
                              line.startsWith('-') ? 'diff-del' :
                              line.startsWith('@@') ? 'diff-context' : '';
            // Escape HTML to prevent XSS
            const escapedLine = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return `<span class="${lineClass}">${escapedLine}</span>`;
        }).join('\n');
    };
    
    const renderList = (listElement, items) => {
        listElement.innerHTML = '';
        if (items && items.length > 0) {
            items.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                listElement.appendChild(li);
            });
        } else {
            const li = document.createElement('li');
            li.textContent = 'None';
            li.style.fontStyle = 'italic';
            listElement.appendChild(li);
        }
    };

    const renderPlanning = (data) => {
        showView('planning');
        elements.planningProgress.style.width = `${data.progress || 0}%`;
        elements.timeline.innerHTML = '';
        if (data.tool_logs) {
            data.tool_logs.forEach(log => {
                const item = document.createElement('div');
                item.className = 'timeline-item';
                item.innerHTML = `<strong>${log.tool_name}</strong><pre><code>${JSON.stringify(log.tool_input, null, 2)}</code></pre>`;
                elements.timeline.appendChild(item);
            });
        }
    };

    const renderPlanReview = (data) => {
        if (currentStatus !== 'plan_review') {
            showView('planReview');
            allFiles = data.all_files || [];
            
            elements.planAndReasoning.innerHTML = `
                <h3>Plan</h3>
                <p>${data.plan.replace(/\n/g, '<br>')}</p>
                <h3>Reasoning</h3>
                <p>${data.reasoning.replace(/\n/g, '<br>')}</p>
            `;
            renderList(elements.relevantFilesList, data.relevant_files);
            renderList(elements.filesToEditList, data.files_to_edit);
            renderList(elements.generationOrderList, data.generation_order);
        }
    };

    const renderUserInput = (data) => {
        showView('userInput');
        elements.userInputPrompt.textContent = data.user_request;
    };

    const renderGenerating = (data) => {
        showView('generating');
        const total = data.generation_order.length;
        const completed = data.completed_files.length;
        const progress = total > 0 ? (completed / total) * 100 : 0;

        elements.generationProgress.style.width = `${progress}%`;
        elements.completedFilesCount.textContent = completed;
        elements.totalFilesCount.textContent = total;

        // Only update completed files if the list has changed
        const existingFiles = new Set([...elements.completedFilesContainer.querySelectorAll('details')].map(d => d.dataset.filePath));
        const newFiles = data.completed_files.filter(f => !existingFiles.has(f.file_path));

        newFiles.forEach(file => {
            const details = document.createElement('details');
            details.className = 'generated-file-details';
            details.dataset.filePath = file.file_path;

            const summary = document.createElement('summary');
            summary.textContent = file.file_path;
            
            const content = document.createElement('div');
            content.className = 'generated-file-content';
            content.innerHTML = `
                <div class="card">
                    <h4>Summary</h4>
                    <p>${file.summary.replace(/\n/g, '<br>')}</p>
                </div>
                <div class="card">
                    <h4>Reasoning</h4>
                    <p>${file.reasoning.replace(/\n/g, '<br>')}</p>
                </div>
                <div class="card">
                    <h4>Diff</h4>
                    <div class="diff-container">
                        <pre><code>${renderDiff(file.diff)}</code></pre>
                    </div>
                </div>
            `;
            details.appendChild(summary);
            details.appendChild(content);
            elements.completedFilesContainer.appendChild(details);
        });

        renderList(elements.pendingFilesList, data.pending_files);
    };

    const renderDone = (data) => {
        showView('done');
        elements.doneMessage.textContent = data.message || 'Task completed successfully.';
        if (data.commit_message) {
            elements.commitMessage.innerHTML = `<strong>Commit Message:</strong><pre>${data.commit_message}</pre>`;
        }
        if (pollingInterval) clearInterval(pollingInterval);
    };

    const renderError = (data) => {
        showView('error');
        elements.errorMessage.textContent = data.error || 'An unknown error occurred.';
        if (pollingInterval) clearInterval(pollingInterval);
    };

    const updateUI = (data) => {
        if (!data || !data.status) return;

        switch (data.status) {
            case 'planning':
                renderPlanning(data);
                break;
            case 'plan_review':
                renderPlanReview(data);
                break;
            case 'user_input_required':
                renderUserInput(data);
                break;
            case 'generating':
                renderGenerating(data);
                break;
            case 'done':
                renderDone(data);
                break;
            case 'error':
                renderError(data);
                break;
        }
        currentStatus = data.status;
    };

    // --- EVENT LISTENERS ---
    elements.approveBtn.addEventListener('click', () => {
        const contextFiles = [...elements.userContextFilesList.querySelectorAll('li')].map(li => li.textContent);
        sendAction('/approve', { context_files: contextFiles });
    });

    elements.rejectBtn.addEventListener('click', () => {
        sendAction('/reject');
    });

    elements.sendFeedbackBtn.addEventListener('click', () => {
        const feedback = elements.feedbackInput.value;
        if (feedback) {
            sendAction('/feedback', { feedback });
            elements.feedbackInput.value = '';
        }
    });
    
    elements.sendUserInputBtn.addEventListener('click', () => {
        const userInput = elements.userInputArea.value;
        if (userInput) {
            sendAction('/user_input', { user_input: userInput });
            elements.userInputArea.value = '';
        }
    });

    // Autocomplete Logic
    const filterFiles = (input) => {
        if (!input) return [];
        return allFiles.filter(file => file.toLowerCase().includes(input.toLowerCase()));
    };

    const showAutocomplete = (matches) => {
        elements.autocompleteList.innerHTML = '';
        if (matches.length > 0) {
            matches.slice(0, 10).forEach(match => { // Show max 10 matches
                const item = document.createElement('div');
                item.textContent = match;
                item.addEventListener('click', () => {
                    elements.contextFileInput.value = match;
                    elements.autocompleteList.innerHTML = '';
                    elements.autocompleteList.classList.add('hidden');
                });
                elements.autocompleteList.appendChild(item);
            });
            elements.autocompleteList.classList.remove('hidden');
        } else {
            elements.autocompleteList.classList.add('hidden');
        }
    };

    elements.contextFileInput.addEventListener('input', (e) => {
        const matches = filterFiles(e.target.value);
        showAutocomplete(matches);
    });

    document.addEventListener('click', (e) => {
        if (e.target !== elements.contextFileInput) {
            elements.autocompleteList.classList.add('hidden');
        }
    });

    elements.addContextFileBtn.addEventListener('click', () => {
        const fileName = elements.contextFileInput.value.trim();
        if (fileName && allFiles.includes(fileName)) {
            const li = document.createElement('li');
            li.textContent = fileName;
            const removeBtn = document.createElement('button');
            removeBtn.textContent = 'x';
            removeBtn.addEventListener('click', () => li.remove());
            li.appendChild(removeBtn);
            elements.userContextFilesList.appendChild(li);
            elements.contextFileInput.value = '';
        }
    });

    // --- INITIALIZATION ---
    pollStatus(); // Initial call
    pollingInterval = setInterval(pollStatus, 2000); // Poll every 2 seconds
});

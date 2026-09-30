export interface paths {
    "/api/application/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Application Activity
         * @description Return safe, process-local technical activity after a cursor.
         */
        get: operations["application_activity_api_application_activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/application/preferences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Application Preferences */
        get: operations["application_preferences_api_application_preferences_get"];
        /** Update Application Preferences */
        put: operations["update_application_preferences_api_application_preferences_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/application/quit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Quit Application */
        post: operations["quit_application_api_application_quit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/application/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Application Status */
        get: operations["application_status_api_application_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/defaults/material": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Default Material */
        get: operations["get_default_material_api_defaults_material_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Discussion Agents
         * @description Replace the complete editable agent roster for the open discussion.
         */
        put: operations["update_discussion_agents_api_discussions_agents_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Discussion Generation */
        post: operations["cancel_discussion_generation_api_discussions_cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/context-estimate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Estimate Discussion Context
         * @description Estimate the current first-round request without generating text.
         */
        post: operations["estimate_discussion_context_api_discussions_context_estimate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/continue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Continue Discussion */
        post: operations["continue_discussion_api_discussions_continue_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/defaults/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Default Agents */
        get: operations["get_default_agents_api_discussions_defaults_agents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Discussion
         * @description Export the current discussion as Markdown.
         */
        get: operations["export_discussion_api_discussions_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/messages/{message_id}/context-inclusion": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Message Context Inclusion
         * @description Update one current-round message's next-round context inclusion flag.
         */
        put: operations["update_message_context_inclusion_api_discussions_messages__message_id__context_inclusion_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/messages/{message_id}/note": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Set Message Note */
        post: operations["set_message_note_api_discussions_messages__message_id__note_post"];
        /** Delete Message Note */
        delete: operations["delete_message_note_api_discussions_messages__message_id__note_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/next-round-configuration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Next Round Configuration
         * @description Atomically replace all editable settings for the next round.
         */
        put: operations["update_next_round_configuration_api_discussions_next_round_configuration_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/perspectives": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Discussion Perspectives */
        get: operations["list_discussion_perspectives_api_discussions_perspectives_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/provider-provenance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Provider Provenance */
        get: operations["get_provider_provenance_api_discussions_provider_provenance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reset Discussion */
        post: operations["reset_discussion_api_discussions_reset_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/session-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Discussion Session Types */
        get: operations["list_discussion_session_types_api_discussions_session_types_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Discussion */
        post: operations["start_discussion_api_discussions_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/state": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Discussion State */
        get: operations["get_discussion_state_api_discussions_state_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/discussions/synthesis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Discussion Synthesis
         * @description Replace the persisted synthesis configuration between rounds.
         */
        put: operations["update_discussion_synthesis_api_discussions_synthesis_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Healthcheck */
        get: operations["healthcheck_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Hosts */
        get: operations["list_hosts_api_hosts_get"];
        put?: never;
        /**
         * Create Host
         * @description Add a new LLM host to the known-host catalogue.
         */
        post: operations["create_host_api_hosts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Delete Host
         * @description Delete one preflighted host and restore memory if durable persistence fails.
         */
        post: operations["delete_host_api_hosts_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/delete-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Preview Host Deletion
         * @description Freeze the secret-free consequences shown before destructive confirmation.
         */
        post: operations["preview_host_deletion_api_hosts_delete_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/test-connection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Draft Host
         * @description Test an unsaved host using only the details supplied by the dialog.
         */
        post: operations["test_draft_host_api_hosts_test_connection_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/{index}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Host
         * @description Update one host while preserving omitted and unrecognized fields.
         */
        put: operations["update_host_api_hosts__index__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/{index}/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Host Models
         * @description Load currently advertised model IDs from a configured host.
         */
        get: operations["get_host_models_api_hosts__index__models_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/{index}/reset-managed-local-ai": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reset Managed Local Ai Host
         * @description Restore the factory configuration of the verified managed host.
         */
        post: operations["reset_managed_local_ai_host_api_hosts__index__reset_managed_local_ai_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/hosts/{index}/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Host
         * @description Test a saved host or an edit draft without mutating the catalogue.
         *
         *     An edit dialog never receives the stored key. An omitted or blank draft key
         *     therefore reuses the saved key only while testing the unchanged saved URL;
         *     a non-blank draft key is used only for the test and is never persisted.
         */
        post: operations["test_host_api_hosts__index__test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/diagnostics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Local Ai Diagnostics
         * @description Return a bounded diagnostic record with managed file paths redacted.
         */
        get: operations["get_local_ai_diagnostics_api_local_ai_diagnostics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/imports/finalize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Finalize Local Ai Model Import */
        post: operations["finalize_local_ai_model_import_api_local_ai_imports_finalize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/imports/{import_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Abort Local Ai Model Import */
        delete: operations["abort_local_ai_model_import_api_local_ai_imports__import_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/imports/{import_id}/{artifact}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Upload Local Ai Import Part
         * @description Stream one selected artifact without multipart buffering in memory.
         */
        put: operations["upload_local_ai_import_part_api_local_ai_imports__import_id___artifact__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Install Local Ai */
        post: operations["install_local_ai_api_local_ai_install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/install/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Local Ai Install */
        post: operations["cancel_local_ai_install_api_local_ai_install_cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/models/delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Delete Local Ai Model */
        post: operations["delete_local_ai_model_api_local_ai_models_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/models/import-from-directory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Local Ai Model From Directory
         * @description Detect and copy one exact catalog model from a selected portable bundle.
         */
        post: operations["import_local_ai_model_from_directory_api_local_ai_models_import_from_directory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/models/reveal-directory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reveal Local Ai Models Directory
         * @description Open the managed local AI models directory without returning its path.
         */
        post: operations["reveal_local_ai_models_directory_api_local_ai_models_reveal_directory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/models/{model_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Local Ai Model By Id */
        delete: operations["delete_local_ai_model_by_id_api_local_ai_models__model_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/models/{model_id}/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Begin Local Ai Model Import
         * @description Create a private staging area for a browser-selected portable bundle.
         */
        post: operations["begin_local_ai_model_import_api_local_ai_models__model_id__import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/models/{model_id}/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Install Local Ai Model */
        post: operations["install_local_ai_model_api_local_ai_models__model_id__install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/preferred-model": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Set Local Ai Preferred Model
         * @description Persist the model used by the managed Integrated AI host on its next start.
         */
        put: operations["set_local_ai_preferred_model_api_local_ai_preferred_model_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/runtime": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Local Ai Runtime */
        delete: operations["delete_local_ai_runtime_api_local_ai_runtime_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/runtime/update": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Local Ai Runtime */
        post: operations["update_local_ai_runtime_api_local_ai_runtime_update_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Local Ai */
        post: operations["start_local_ai_api_local_ai_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Local Ai Status */
        get: operations["get_local_ai_status_api_local_ai_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/local-ai/stop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Stop Local Ai */
        post: operations["stop_local_ai_api_local_ai_stop_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/material/token-estimate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Estimate Material Tokens */
        post: operations["estimate_material_tokens_api_material_token_estimate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/material/with-line-numbers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Line Numbers */
        post: operations["add_line_numbers_api_material_with_line_numbers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/preview/templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Preview Templates */
        get: operations["list_preview_templates_api_preview_templates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/preview/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Render Preview */
        get: operations["render_preview_api_preview__template_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/globals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Prompt Globals
         * @description List the existing global prompt blocks.
         *
         *     Source is the live :class:`PromptRepository`; only existing
         *     ``<global>`` blocks are surfaced. The on-disk ``source_file`` path
         *     is never included in the response.
         */
        get: operations["list_prompt_globals_api_prompts_globals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/globals/restore-defaults": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Default Globals
         * @description Restore all shipped global blocks while preserving custom blocks.
         */
        post: operations["restore_default_globals_api_prompts_globals_restore_defaults_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/globals/reveal-directory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reveal Globals Directory Endpoint
         * @description Open the validated global-prompts folder without returning its path.
         */
        post: operations["reveal_globals_directory_endpoint_api_prompts_globals_reveal_directory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/globals/{global_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Prompt Global
         * @description Update the ``label`` and ``content`` of an existing global block.
         *
         *     ``scope`` is read-only and rejected at the schema level (extra
         *     field). Path-traversal attempts are rejected before any file I/O.
         *     The on-disk file is rewritten atomically; only the targeted
         *     ``<global>`` block is mutated and the full document is validated
         *     as well-formed XML before the swap.
         */
        put: operations["update_prompt_global_api_prompts_globals__global_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/globals/{global_id}/restore-default": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Default Global
         * @description Restore one shipped global block after full baseline validation.
         */
        post: operations["restore_default_global_api_prompts_globals__global_id__restore_default_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Roles
         * @description List all prompt templates with their editable status.
         */
        get: operations["list_roles_api_prompts_roles_get"];
        put?: never;
        /**
         * Create Role
         * @description Create a new role POML file in the roles directory.
         */
        post: operations["create_role_api_prompts_roles_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/roles/restore-defaults": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Default Roles
         * @description Atomically restore every baseline POML into the active roles directory.
         *
         *     Recreates missing shipped roles, overwrites edited shipped roles, and leaves
         *     custom (non-baseline) active roles untouched. Fails clearly (non-2xx) and
         *     does not mutate the active directory if the baseline directory is missing,
         *     empty, or any baseline POML fails to parse.
         */
        post: operations["restore_default_roles_api_prompts_roles_restore_defaults_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/roles/reveal-directory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reveal Roles Directory Endpoint
         * @description Open the validated active roles directory without disclosing its path.
         */
        post: operations["reveal_roles_directory_endpoint_api_prompts_roles_reveal_directory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/roles/{role_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Role
         * @description Get a single prompt template by ID.
         */
        get: operations["get_role_api_prompts_roles__role_id__get"];
        /**
         * Update Role
         * @description Update an existing role's POML file.
         */
        put: operations["update_role_api_prompts_roles__role_id__put"];
        post?: never;
        /**
         * Delete Role
         * @description Delete a role's POML file.
         */
        delete: operations["delete_role_api_prompts_roles__role_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/roles/{role_id}/restore-default": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Default Role
         * @description Atomically restore one shipped role from its exact baseline file.
         */
        post: operations["restore_default_role_api_prompts_roles__role_id__restore_default_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/roles/{role_id}/reveal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reveal Role Endpoint
         * @description Reveal one validated role file without exposing its path to the client.
         *
         *     Validation happens before process launch: an invalid id returns 422, a
         *     missing or out-of-root file returns 404, and launch failures return 502
         *     without command or path details.
         */
        post: operations["reveal_role_endpoint_api_prompts_roles__role_id__reveal_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/session-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Prompt Session Types
         * @description List all session types with the editor-relevant fields.
         */
        get: operations["list_prompt_session_types_api_prompts_session_types_get"];
        put?: never;
        /**
         * Create Prompt Session Type
         * @description Create a new session type file and reload the live service.
         */
        post: operations["create_prompt_session_type_api_prompts_session_types_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/session-types/restore-defaults": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Default Session Types
         * @description Restore every validated shipped session file, preserving custom files.
         */
        post: operations["restore_default_session_types_api_prompts_session_types_restore_defaults_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/session-types/reveal-directory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reveal Session Types Directory Endpoint
         * @description Open the validated active session-types directory without returning its path.
         */
        post: operations["reveal_session_types_directory_endpoint_api_prompts_session_types_reveal_directory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/session-types/{key}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Prompt Session Type
         * @description Update an existing session type. The URL key is immutable.
         */
        put: operations["update_prompt_session_type_api_prompts_session_types__key__put"];
        post?: never;
        /**
         * Delete Prompt Session Type
         * @description Delete a custom session type; shipped types remain recoverable defaults.
         */
        delete: operations["delete_prompt_session_type_api_prompts_session_types__key__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prompts/session-types/{key}/restore-default": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Default Session Type
         * @description Restore one shipped session file without inspecting unrelated baselines.
         */
        post: operations["restore_default_session_type_api_prompts_session_types__key__restore_default_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quick-actions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Quick Actions */
        get: operations["list_quick_actions_api_quick_actions_get"];
        put?: never;
        /** Create Quick Action */
        post: operations["create_quick_action_api_quick_actions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quick-actions/restore-defaults": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Default Quick Actions */
        post: operations["restore_default_quick_actions_api_quick_actions_restore_defaults_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quick-actions/{action_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Quick Action */
        put: operations["update_quick_action_api_quick_actions__action_id__put"];
        post?: never;
        /** Delete Quick Action */
        delete: operations["delete_quick_action_api_quick_actions__action_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quick-actions/{action_id}/restore-default": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Default Quick Action */
        post: operations["restore_default_quick_action_api_quick_actions__action_id__restore_default_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sessions */
        get: operations["list_sessions_api_sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/bulk-delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bulk Delete Sessions */
        post: operations["bulk_delete_sessions_api_sessions_bulk_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{file_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Session */
        delete: operations["delete_session_api_sessions__file_id__delete"];
        options?: never;
        head?: never;
        /** Rename Session */
        patch: operations["rename_session_api_sessions__file_id__patch"];
        trace?: never;
    };
    "/api/sessions/{file_id}/favorite": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Session Favorite */
        put: operations["set_session_favorite_api_sessions__file_id__favorite_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{file_id}/open": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Open Session */
        post: operations["open_session_api_sessions__file_id__open_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{file_id}/reveal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reveal Session */
        post: operations["reveal_session_api_sessions__file_id__reveal_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AgentConfigModel */
        AgentConfigModel: {
            /** Api Host */
            api_host?: string | null;
            /** Api Key */
            api_key?: string | null;
            /** Client Id */
            client_id: string;
            /**
             * Color
             * @default #333333
             */
            color: string;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Host Configuration Id */
            host_configuration_id?: string | null;
            /** Host Label */
            host_label?: string | null;
            /** Llm Id */
            llm_id?: string | null;
            /** Max Tokens */
            max_tokens?: number | null;
            /** Name */
            name: string;
            /** Perspective Number */
            perspective_number: number;
            /** Prompt Id */
            prompt_id?: string | null;
            /** Temperature */
            temperature?: number | null;
        };
        /**
         * AgentMessageSnapshotModel
         * @description An agent result with its required stable roster identity.
         */
        AgentMessageSnapshotModel: {
            /** Agent Index */
            agent_index: number;
            /** Agent Name */
            agent_name: string;
            /** Client Id */
            client_id: string;
            /** Color */
            color: string;
            /** Completion Tokens */
            completion_tokens?: number | null;
            /** Content */
            content: string;
            /** Context Tokens Exact */
            context_tokens_exact?: boolean | null;
            /** Context Usage Available */
            context_usage_available?: boolean | null;
            /** Context Window Tokens */
            context_window_tokens?: number | null;
            /** Error */
            error?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Error Params */
            error_params?: {
                [key: string]: unknown;
            };
            /** Id */
            id: string;
            /**
             * Include In Agent Context
             * @default true
             */
            include_in_agent_context: boolean;
            /**
             * Include Note In Agent Context
             * @default false
             */
            include_note_in_agent_context: boolean;
            /** Input Context Tokens */
            input_context_tokens?: number | null;
            /**
             * Note
             * @default
             */
            note: string;
            /** Omitted Round Numbers */
            omitted_round_numbers?: number[];
            /** Perspective Number */
            perspective_number: number;
            /** Prompt Tokens */
            prompt_tokens?: number | null;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            role: "agent";
            /** Round Number */
            round_number: number;
            /**
             * Status
             * @default completed
             * @enum {string}
             */
            status: "in_progress" | "completed" | "interrupted" | "failed";
            /** Theory Label */
            theory_label?: string | null;
            /** Total Tokens */
            total_tokens?: number | null;
            /** Usage Available */
            usage_available?: boolean | null;
        };
        /**
         * AgentSnapshotModel
         * @description Non-secret portion of a persisted agent configuration.
         */
        AgentSnapshotModel: {
            /** Api Host */
            api_host?: string | null;
            /** Client Id */
            client_id: string;
            /**
             * Color
             * @default #333333
             */
            color: string;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Host Configuration Id */
            host_configuration_id?: string | null;
            /** Host Label */
            host_label?: string | null;
            /** Llm Id */
            llm_id?: string | null;
            /** Max Tokens */
            max_tokens?: number | null;
            /** Name */
            name: string;
            /** Perspective Number */
            perspective_number: number;
            /** Prompt Id */
            prompt_id?: string | null;
            /** Temperature */
            temperature?: number | null;
        };
        /**
         * ApplicationActivityEvent
         * @description A public, privacy-safe application diagnostic event.
         */
        ApplicationActivityEvent: {
            /** Code */
            code: string;
            /**
             * Level
             * @enum {string}
             */
            level: "info" | "warning" | "error";
            /** Params */
            params: {
                [key: string]: string | number;
            };
            /** Sequence */
            sequence: number;
            /** Timestamp */
            timestamp: string;
        };
        /**
         * ApplicationActivityResponse
         * @description A cursor page from the process-local application activity feed.
         */
        ApplicationActivityResponse: {
            /** Events */
            events: components["schemas"]["ApplicationActivityEvent"][];
            /** Next Cursor */
            next_cursor: number;
            /** Truncated */
            truncated: boolean;
        };
        /**
         * BulkDeleteSessionsRequest
         * @description Selection mode for one locked stored-session bulk deletion.
         */
        BulkDeleteSessionsRequest: {
            /** Expected File Ids */
            expected_file_ids: string[];
            /**
             * Mode
             * @enum {string}
             */
            mode: "all" | "except_favorites";
        };
        /** BulkDeleteSessionsResponse */
        BulkDeleteSessionsResponse: {
            /** Deleted Count */
            deleted_count: number;
            /** Deleted Ids */
            deleted_ids: string[];
            /** Was Open */
            was_open: boolean;
        };
        /** CancelDiscussionResponse */
        CancelDiscussionResponse: {
            /**
             * Status
             * @enum {string}
             */
            status: "cancelling" | "idle";
        };
        /**
         * ContextEstimateRequest
         * @description First-round context estimate for the current Setup draft without generation.
         */
        ContextEstimateRequest: {
            /** Agents */
            agents: components["schemas"]["AgentConfigModel"][];
            /**
             * Material
             * @default
             */
            material: string;
            material_context: components["schemas"]["MaterialContextModel"];
            /**
             * Sequential Mode
             * @default false
             */
            sequential_mode: boolean;
            synthesis: components["schemas"]["SynthesisConfigModel"];
        };
        /**
         * ContextEstimateResponse
         * @description Safe context-budget facts without prompt or material content.
         */
        ContextEstimateResponse: {
            /** Available Input Tokens */
            available_input_tokens?: number | null;
            /** Context Window Tokens */
            context_window_tokens?: number | null;
            /** Estimated Input Tokens */
            estimated_input_tokens?: number | null;
            /** Known */
            known: boolean;
            /**
             * Overflow
             * @default false
             */
            overflow: boolean;
            /** Reserved Output Tokens */
            reserved_output_tokens: number;
        };
        /** ContinueDiscussionRequest */
        ContinueDiscussionRequest: {
            /** Agents */
            agents: components["schemas"]["AgentConfigModel"][];
            /** Focus Segment */
            focus_segment?: string | null;
            provider_rebind?: components["schemas"]["ProviderRebindRequest"] | null;
            /**
             * Sequential Mode
             * @default false
             */
            sequential_mode: boolean;
            /** User Input */
            user_input: string;
        };
        /**
         * DefaultMaterialResponse
         * @description The shipped starter material exposed to a fresh setup draft.
         */
        DefaultMaterialResponse: {
            /** Material */
            material: string;
            /** Material Type */
            material_type: string;
        };
        /**
         * DeletePromptConfigurationResponse
         * @description Identifier of one deleted custom prompt configuration item.
         */
        DeletePromptConfigurationResponse: {
            /** Deleted */
            deleted: string;
        };
        /** DeleteSessionResponse */
        DeleteSessionResponse: {
            /** Deleted */
            deleted: boolean;
            /** Deleted Count */
            deleted_count: number;
            /** Deleted Ids */
            deleted_ids: string[];
            /** Was Open */
            was_open: boolean;
        };
        /** DetectedModelImportJobResponse */
        DetectedModelImportJobResponse: {
            /** Job Id */
            job_id: string;
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
        };
        /**
         * DiscussionMessageResponse
         * @description Current in-memory discussion message returned by the state route.
         */
        DiscussionMessageResponse: {
            /** Agent Index */
            agent_index?: number | null;
            /** Agent Name */
            agent_name?: string | null;
            /** Client Id */
            client_id?: string | null;
            /** Color */
            color?: string | null;
            /** Completion Tokens */
            completion_tokens?: number | null;
            /** Content */
            content: string;
            /** Context Tokens Exact */
            context_tokens_exact?: boolean | null;
            /** Context Usage Available */
            context_usage_available?: boolean | null;
            /** Context Window Tokens */
            context_window_tokens?: number | null;
            /** Error */
            error?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Error Params */
            error_params?: {
                [key: string]: unknown;
            };
            /** Id */
            id: string;
            /**
             * Include In Agent Context
             * @default true
             */
            include_in_agent_context: boolean;
            /** Include Note In Agent Context */
            include_note_in_agent_context?: boolean | null;
            /** Input Context Tokens */
            input_context_tokens?: number | null;
            /**
             * Note
             * @default
             */
            note: string;
            /** Omitted Round Numbers */
            omitted_round_numbers?: number[];
            /** Perspective Number */
            perspective_number?: number | null;
            /** Prompt Tokens */
            prompt_tokens?: number | null;
            /**
             * Role
             * @enum {string}
             */
            role: "user" | "agent" | "synthesis" | "system";
            /** Round Number */
            round_number: number;
            /**
             * Status
             * @default completed
             * @enum {string}
             */
            status: "in_progress" | "completed" | "interrupted" | "failed";
            /** Theory Label */
            theory_label?: string | null;
            /** Total Tokens */
            total_tokens?: number | null;
            /** Usage Available */
            usage_available?: boolean | null;
        };
        /**
         * DiscussionSessionTypeResponse
         * @description Setup metadata for one current session type.
         */
        DiscussionSessionTypeResponse: {
            /** Description */
            description?: string | null;
            /** Inputs */
            inputs: components["schemas"]["SessionInputDefinition"][];
            /** Key */
            key: string;
            /** Label */
            label: string;
        };
        /**
         * DiscussionStateResponse
         * @description The active in-memory discussion state.
         */
        DiscussionStateResponse: {
            /** Has Active Discussion */
            has_active_discussion: boolean;
            /** Has Errors */
            has_errors: boolean;
            /** Initial Question */
            initial_question: string;
            /** Material */
            material: string;
            /** Messages */
            messages: components["schemas"]["DiscussionMessageResponse"][];
            /** Round Number */
            round_number: number;
            /** Round Status */
            round_status?: ("in_progress" | "completed" | "interrupted" | "failed") | null;
        };
        /**
         * DiscussionStreamEventResponse
         * @description One JSON payload emitted on the discussion SSE stream.
         */
        DiscussionStreamEventResponse: {
            /** Agent Index */
            agent_index?: number | null;
            /** Agent Name */
            agent_name?: string | null;
            /** Available */
            available?: boolean | null;
            /** Client Id */
            client_id?: string | null;
            /** Color */
            color?: string | null;
            /** Completion Tokens */
            completion_tokens?: number | null;
            /** Content */
            content?: string | null;
            /** Context Tokens */
            context_tokens?: number | null;
            /** Context Tokens Exact */
            context_tokens_exact?: boolean | null;
            /** Context Usage Available */
            context_usage_available?: boolean | null;
            /** Context Window Tokens */
            context_window_tokens?: number | null;
            /** Error */
            error?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Error Params */
            error_params?: {
                [key: string]: unknown;
            } | null;
            /** Exact */
            exact?: boolean | null;
            /** File Id */
            file_id?: string | null;
            /** Input Tokens */
            input_tokens?: number | null;
            /** Is Complete */
            is_complete?: boolean | null;
            /** Message */
            message?: string | null;
            /** Message Id */
            message_id?: string | null;
            /** Omitted Round Numbers */
            omitted_round_numbers?: number[] | null;
            /** Perspective Number */
            perspective_number?: number | null;
            /** Prompt Tokens */
            prompt_tokens?: number | null;
            /** Round Number */
            round_number?: number | null;
            /** Status */
            status?: ("in_progress" | "completed" | "interrupted" | "failed") | null;
            /** Text */
            text?: string | null;
            /** Theory Label */
            theory_label?: string | null;
            /** Title */
            title?: string | null;
            /** Total Tokens */
            total_tokens?: number | null;
            /**
             * Type
             * @enum {string}
             */
            type: "discussion_started" | "user_message" | "context_usage" | "agent_start" | "chunk" | "agent_complete" | "synthesis_start" | "synthesis_chunk" | "synthesis_complete" | "synthesis_error" | "all_complete" | "error";
            /** Usage Available */
            usage_available?: boolean | null;
        };
        /**
         * DraftHostTestRequest
         * @description Connection details used only for testing an unsaved external host.
         */
        DraftHostTestRequest: {
            /**
             * Api Key
             * @description Optional API key
             */
            api_key?: string | null;
            /**
             * Url
             * @description Host URL (http:// or https://)
             */
            url: string;
        };
        /** GlobalBlockResponse */
        GlobalBlockResponse: {
            /** Content */
            content: string;
            /** Id */
            id: string;
            /** Is Shipped */
            is_shipped: boolean;
            /** Label */
            label: string;
            /**
             * Origin
             * @enum {string}
             */
            origin: "shipped_default" | "shipped_modified" | "custom";
            /** Scope */
            scope: string | null;
        };
        /**
         * GlobalUpdateRequest
         * @description Body for ``PUT /api/prompts/globals/{global_id}``.
         *
         *     Only ``label`` and ``content`` are mutable. ``scope`` is
         *     intentionally read-only (it changes the block's consumer
         *     eligibility), so the schema rejects any extra field with a 422.
         */
        GlobalUpdateRequest: {
            /**
             * Content
             * @default
             */
            content: string;
            /** Label */
            label: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * HostCreateRequest
         * @description Body for POST /api/hosts.
         */
        HostCreateRequest: {
            /**
             * Api Key
             * @description Optional API key
             */
            api_key?: string | null;
            /**
             * Is Favorite
             * @description Whether this is the preferred external host
             * @default false
             */
            is_favorite: boolean;
            /**
             * Kind
             * @description Optional host kind marker
             */
            kind?: string | null;
            /**
             * Label
             * @description Human-readable label
             */
            label: string;
            /**
             * Model
             * @description Default model name
             */
            model: string;
            /**
             * Model Context Tokens
             * @description Optional context-window limit by selected model ID
             */
            model_context_tokens?: {
                [key: string]: number;
            };
            /**
             * Models
             * @description Selectable model names
             */
            models?: string[] | null;
            /**
             * Url
             * @description Host URL (http:// or https://)
             */
            url: string;
        };
        /**
         * HostDeletePreviewRequest
         * @description Stable host identity submitted before destructive confirmation.
         */
        HostDeletePreviewRequest: {
            /** Label */
            label: string;
        };
        /**
         * HostDeletePreviewResponse
         * @description Secret-free consequences frozen for one host deletion confirmation.
         */
        HostDeletePreviewResponse: {
            /** Credential Will Be Removed */
            credential_will_be_removed: boolean;
            /** Is Preferred */
            is_preferred: boolean;
            /** Label */
            label: string;
            /** Revision */
            revision: string;
            /** Saved Sessions */
            saved_sessions: components["schemas"]["SavedSessionHostDependency"][];
        };
        /**
         * HostDeleteRequest
         * @description Frozen preflight identity required to delete one configured host.
         */
        HostDeleteRequest: {
            /** Label */
            label: string;
            /** Revision */
            revision: string;
        };
        /**
         * HostDeleteResponse
         * @description Bounded authoritative result of one host deletion.
         */
        HostDeleteResponse: {
            /** Credential Removed */
            credential_removed: boolean;
            /** Deleted */
            deleted: boolean;
            /** Label */
            label: string;
        };
        /**
         * HostInfoResponse
         * @description Path- and secret-free configured host metadata.
         */
        HostInfoResponse: {
            /** Configuration Id */
            configuration_id: string;
            /** Context Tokens */
            context_tokens?: number | null;
            /** Has Api Key */
            has_api_key: boolean;
            /** Is Favorite */
            is_favorite?: boolean | null;
            /** Kind */
            kind?: string | null;
            /** Label */
            label: string;
            /** Model */
            model: string;
            /** Model Context Tokens */
            model_context_tokens?: {
                [key: string]: number;
            };
            /** Models */
            models: string[];
            /** Url */
            url: string;
        };
        /** HostModelsResponse */
        HostModelsResponse: {
            /** Models */
            models: string[];
        };
        /**
         * HostUpdateRequest
         * @description Body for PUT /api/hosts/{index}; omitted fields are preserved.
         */
        HostUpdateRequest: {
            /**
             * Api Key
             * @description New API key — omit to keep, null/empty to clear
             */
            api_key?: string | null;
            /**
             * Configuration Id
             * @description Expected saved host identity
             */
            configuration_id: string;
            /**
             * Is Favorite
             * @description Set preferred external host
             */
            is_favorite?: boolean | null;
            /**
             * Kind
             * @description Optional host kind marker
             */
            kind?: string | null;
            /**
             * Label
             * @description New label
             */
            label?: string | null;
            /**
             * Model
             * @description New model name
             */
            model?: string | null;
            /**
             * Model Context Tokens
             * @description Replace optional context-window limits by selected model ID
             */
            model_context_tokens?: {
                [key: string]: number;
            } | null;
            /**
             * Models
             * @description Selectable model names
             */
            models?: string[] | null;
            /**
             * Url
             * @description New URL
             */
            url?: string | null;
        };
        /** ImportStartResponse */
        ImportStartResponse: {
            /** Import Id */
            import_id: string;
        };
        /** JobResponse */
        JobResponse: {
            /** Job Id */
            job_id: string;
        };
        /**
         * LocalAIBackgroundImportRequest
         * @description Optional explicit source directory for the manual-path option.
         */
        LocalAIBackgroundImportRequest: {
            /** Source Path */
            source_path?: string | null;
        };
        /** LocalAICancelRequest */
        LocalAICancelRequest: {
            /** Job Id */
            job_id: string;
        };
        /** LocalAIDeleteModelRequest */
        LocalAIDeleteModelRequest: {
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
        };
        /** LocalAIDiagnosticsResponse */
        LocalAIDiagnosticsResponse: {
            /** Command Kind */
            command_kind?: ("active" | "next_start" | "last_attempt") | null;
            /** Command Reference */
            command_reference?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Exit Code */
            exit_code?: number | null;
            /** Log Tail */
            log_tail?: string[];
            runtime_selection_diagnostics: components["schemas"]["LocalAIRuntimeSelectionDiagnosticsResponse"];
        };
        /** LocalAIImportFilesResponse */
        LocalAIImportFilesResponse: {
            /** Draft */
            draft: string;
            /** Main */
            main: string;
        };
        /** LocalAIImportFinalizeRequest */
        LocalAIImportFinalizeRequest: {
            /** Import Id */
            import_id: string;
        };
        /** LocalAIInstallOptions */
        LocalAIInstallOptions: {
            /**
             * Start After Install
             * @default false
             */
            start_after_install: boolean;
        };
        /** LocalAIInstallRequest */
        LocalAIInstallRequest: {
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
            /**
             * Start After Install
             * @default false
             */
            start_after_install: boolean;
        };
        /** LocalAIModelInventoryResponse */
        LocalAIModelInventoryResponse: {
            /** Api Alias */
            api_alias?: string | null;
            /** Draft Bytes */
            draft_bytes?: number | null;
            import_files?: components["schemas"]["LocalAIImportFilesResponse"] | null;
            /** Installed */
            installed: boolean;
            /**
             * Integrity
             * @enum {string}
             */
            integrity: "unknown" | "verified" | "failed";
            /** Model Bytes */
            model_bytes?: number | null;
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
        };
        /** LocalAIPreferredModelRequest */
        LocalAIPreferredModelRequest: {
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
        };
        /** LocalAIRuntimeSelectionAttempt */
        LocalAIRuntimeSelectionAttempt: {
            /** Profile */
            profile: string;
            /** Reason */
            reason?: ("missing_runtime_library" | "driver_unavailable" | "no_gpu" | "probe_timeout" | "probe_failed" | "malformed_output" | "model_offload_failed" | "runtime_launch_failed" | "runtime_options_unavailable" | "runtime_incompatible" | "accelerator_failed" | "insufficient_resources" | "port_conflict") | null;
            /**
             * Result
             * @enum {string}
             */
            result: "accepted" | "rejected" | "selected";
            /**
             * Stage
             * @enum {string}
             */
            stage: "device_probe" | "runtime_preflight" | "model_readiness" | "runtime_update";
        };
        /** LocalAIRuntimeSelectionDiagnosticsResponse */
        LocalAIRuntimeSelectionDiagnosticsResponse: {
            record?: components["schemas"]["LocalAIRuntimeSelectionRecord"] | null;
            /**
             * State
             * @enum {string}
             */
            state: "available" | "missing" | "invalid";
        };
        /**
         * LocalAIRuntimeSelectionRecord
         * @description Exact allowlist of fields written by the bounded runtime-selection recorder.
         */
        LocalAIRuntimeSelectionRecord: {
            /** Attempts */
            attempts: components["schemas"]["LocalAIRuntimeSelectionAttempt"][];
            /**
             * Operation
             * @enum {string}
             */
            operation: "model_install" | "runtime_update";
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "incomplete" | "selected";
            /** Selected Profile */
            selected_profile?: string | null;
            /**
             * Version
             * @constant
             */
            version: 1;
        };
        /** LocalAIRuntimeSelectionResponse */
        LocalAIRuntimeSelectionResponse: {
            /** Acceleration Confirmed */
            acceleration_confirmed: boolean;
            /** Accelerator Label */
            accelerator_label?: string | null;
            /** Decision Basis */
            decision_basis?: ("detected compatible runtime" | "safe CPU fallback") | null;
            /** Engine Name */
            engine_name?: ("llama-server" | "llama-server.exe") | null;
            /** Runtime Installed */
            runtime_installed?: boolean | null;
            /** Runtime Profile */
            runtime_profile?: string | null;
        };
        /** LocalAIStartRequest */
        LocalAIStartRequest: {
            /**
             * Context Tokens
             * @default 32768
             */
            context_tokens: number;
            /**
             * Model Id
             * @enum {string}
             */
            model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
            /** Mtp Draft Tokens */
            mtp_draft_tokens?: (1 | 2 | 3 | 4 | 5 | 6) | null;
            /**
             * Mtp Enabled
             * @default false
             */
            mtp_enabled: boolean;
        };
        /**
         * LocalAIStatusResponse
         * @description Sanitized Integrated AI status with its complete model inventory.
         */
        LocalAIStatusResponse: {
            /** Accelerator Label */
            accelerator_label?: string | null;
            /** Available Disk Bytes */
            available_disk_bytes?: number | null;
            /** Context Tokens */
            context_tokens?: number | null;
            /** Cpu Label */
            cpu_label?: string | null;
            /** Download Bytes */
            download_bytes: number;
            /** Download Phase */
            download_phase?: ("preparing" | "runtime" | "main_model" | "mtp_drafter" | "finalizing") | null;
            /** Download Total */
            download_total: number;
            /** Draft Bytes */
            draft_bytes?: number | null;
            /** Error Code */
            error_code?: string | null;
            /** Gpu Label */
            gpu_label?: string | null;
            /** Host */
            host?: string | null;
            /** Host Ready */
            host_ready: boolean;
            /** Import Bytes */
            import_bytes?: number | null;
            /** Import Phase */
            import_phase?: ("copying" | "verifying") | null;
            /** Import Total */
            import_total?: number | null;
            /** Inference Memory Gb */
            inference_memory_gb?: number | null;
            /** Inference Memory Kind */
            inference_memory_kind?: ("ram" | "vram" | "unified") | null;
            /**
             * Integrity
             * @enum {string}
             */
            integrity: "unknown" | "verified" | "failed";
            /** Job Id */
            job_id?: string | null;
            /** Logical Cpu Count */
            logical_cpu_count?: number | null;
            /** Message */
            message?: string | null;
            /** Model Bytes */
            model_bytes?: number | null;
            /** Model Id */
            model_id?: ("gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b") | null;
            /** Model Name */
            model_name?: string | null;
            /** Models */
            models: components["schemas"]["LocalAIModelInventoryResponse"][];
            /** Mtp Draft Tokens */
            mtp_draft_tokens?: number | null;
            /** Mtp Enabled */
            mtp_enabled?: boolean | null;
            /** Operation Kind */
            operation_kind?: ("model_download" | "model_import" | "runtime_update") | null;
            /** Operation Model Id */
            operation_model_id?: ("gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b") | null;
            /** Operation State */
            operation_state?: ("downloading" | "importing" | "cancelling" | "error") | null;
            /** Os Label */
            os_label?: string | null;
            /** Port */
            port?: number | null;
            /** Preferred Model Id */
            preferred_model_id?: ("gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b") | null;
            /** Ram Gb */
            ram_gb?: number | null;
            /** Runtime Installed */
            runtime_installed?: boolean | null;
            runtime_selection: components["schemas"]["LocalAIRuntimeSelectionResponse"];
            /**
             * State
             * @enum {string}
             */
            state: "not_installed" | "downloading" | "importing" | "installed" | "starting" | "running" | "sleeping" | "error" | "stopped" | "cancelling" | "cancelled";
        };
        /** MaterialContextModel */
        MaterialContextModel: {
            input_values: components["schemas"]["SessionInputValuesModel"];
            /** Material Type */
            material_type: string;
            /** Session Type */
            session_type: string;
            /** Target Language */
            target_language: string;
        };
        /** MaterialContextSnapshotModel */
        MaterialContextSnapshotModel: {
            /** Include Unchanged Research Material Context In Prompt */
            include_unchanged_research_material_context_in_prompt: boolean;
            /** Input Definitions */
            input_definitions: components["schemas"]["SessionInputDefinition"][];
            input_values: components["schemas"]["SessionInputValuesModel"];
            /** Material Type */
            material_type: string;
            /** Session Type */
            session_type: string;
            /** Target Language */
            target_language: string;
        };
        /** MaterialLineNumberRequest */
        MaterialLineNumberRequest: {
            /** Material */
            material: string;
        };
        /** MaterialLineNumberResponse */
        MaterialLineNumberResponse: {
            /** Material */
            material: string;
        };
        /** MaterialTokenEstimateRequest */
        MaterialTokenEstimateRequest: {
            /**
             * Material
             * @default
             */
            material: string;
            /**
             * Material Type
             * @default document
             */
            material_type: string;
        };
        /** MaterialTokenEstimateResponse */
        MaterialTokenEstimateResponse: {
            /** Approximate Tokens */
            approximate_tokens: number;
            /** Tokenizer */
            tokenizer: string;
        };
        /**
         * MessageContextInclusionRequest
         * @description Strict per-message context inclusion contract.
         */
        MessageContextInclusionRequest: {
            /** Include In Agent Context */
            include_in_agent_context: boolean;
        };
        /** MessageContextInclusionResponse */
        MessageContextInclusionResponse: {
            /**
             * Ok
             * @default true
             */
            ok: boolean;
        };
        /**
         * NextRoundAgentConfigModel
         * @description Complete secret-free configuration for one stable session participant.
         */
        NextRoundAgentConfigModel: {
            /** Api Host */
            api_host?: string | null;
            /** Client Id */
            client_id: string;
            /**
             * Color
             * @default #333333
             */
            color: string;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Host Configuration Id */
            host_configuration_id?: string | null;
            /** Llm Id */
            llm_id?: string | null;
            /** Max Tokens */
            max_tokens?: number | null;
            /** Name */
            name: string;
            /** Perspective Number */
            perspective_number: number;
            /** Prompt Id */
            prompt_id?: string | null;
            /** Temperature */
            temperature?: number | null;
        };
        /**
         * NextRoundSynthesisConfigModel
         * @description Complete secret-free synthesis configuration for the next round.
         */
        NextRoundSynthesisConfigModel: {
            /** Api Host */
            api_host: string | null;
            /** Enabled */
            enabled: boolean;
            /** Host Configuration Id */
            host_configuration_id?: string | null;
            /** Llm Id */
            llm_id: string | null;
            /** Temperature */
            temperature: number | null;
        };
        /**
         * NonAgentMessageSnapshotModel
         * @description A user, synthesis, or system event with no roster identity.
         */
        NonAgentMessageSnapshotModel: {
            /** Agent Index */
            agent_index?: null;
            /** Agent Name */
            agent_name?: null;
            /** Client Id */
            client_id?: null;
            /** Color */
            color?: null;
            /** Completion Tokens */
            completion_tokens?: number | null;
            /** Content */
            content: string;
            /** Context Tokens Exact */
            context_tokens_exact?: boolean | null;
            /** Context Usage Available */
            context_usage_available?: boolean | null;
            /** Context Window Tokens */
            context_window_tokens?: number | null;
            /** Error */
            error?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Error Params */
            error_params?: {
                [key: string]: unknown;
            };
            /** Id */
            id: string;
            /**
             * Include In Agent Context
             * @default true
             */
            include_in_agent_context: boolean;
            /**
             * Include Note In Agent Context
             * @default false
             */
            include_note_in_agent_context: boolean;
            /** Input Context Tokens */
            input_context_tokens?: number | null;
            /**
             * Note
             * @default
             */
            note: string;
            /** Omitted Round Numbers */
            omitted_round_numbers?: number[];
            /** Perspective Number */
            perspective_number?: null;
            /** Prompt Tokens */
            prompt_tokens?: number | null;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            role: "synthesis" | "system" | "user";
            /** Round Number */
            round_number: number;
            /**
             * Status
             * @default completed
             * @enum {string}
             */
            status: "in_progress" | "completed" | "interrupted" | "failed";
            /** Theory Label */
            theory_label?: null;
            /** Total Tokens */
            total_tokens?: number | null;
            /** Usage Available */
            usage_available?: boolean | null;
        };
        /** NoteRequest */
        NoteRequest: {
            /**
             * Include Note In Agent Context
             * @default false
             */
            include_note_in_agent_context: boolean;
            /**
             * Note
             * @default
             */
            note: string;
        };
        /**
         * OpenSessionResponse
         * @description Complete path- and secret-free snapshot of an opened session.
         */
        OpenSessionResponse: {
            /** Agents */
            agents: components["schemas"]["AgentSnapshotModel"][];
            /** File Id */
            file_id: string;
            /** Has Active Discussion */
            has_active_discussion: boolean;
            /** Initial Question */
            initial_question: string;
            /** Material */
            material: string;
            material_context: components["schemas"]["MaterialContextSnapshotModel"];
            /** Messages */
            messages: (components["schemas"]["AgentMessageSnapshotModel"] | components["schemas"]["NonAgentMessageSnapshotModel"])[];
            /** Round Number */
            round_number: number;
            /** Round Provider Provenance */
            round_provider_provenance: components["schemas"]["RoundProviderProvenanceResponse"][];
            /** Round Status */
            round_status?: ("in_progress" | "completed" | "interrupted" | "failed") | null;
            /** Sequential Mode */
            sequential_mode: boolean;
            synthesis: components["schemas"]["SynthesisConfigModel"];
            /** Title */
            title: string;
        };
        /**
         * PerspectiveResponse
         * @description One selectable discussion perspective.
         */
        PerspectiveResponse: {
            /** Description */
            description?: string | null;
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** PreviewResult */
        PreviewResult: {
            /** Char Count */
            char_count: number;
            /** Estimated Tokens */
            estimated_tokens: number | null;
            /** Label */
            label: string;
            /** Mode */
            mode: string;
            /** Prompt Sources */
            prompt_sources: components["schemas"]["PromptSource"][];
            /** Scenario */
            scenario: string;
            /** Session Label */
            session_label: string;
            /** Session Type */
            session_type: string;
            /** System Prompt */
            system_prompt: string;
            /** Template Id */
            template_id: string;
            /** Tokenizer Name */
            tokenizer_name: string;
            /** User Prompt */
            user_prompt: string;
        };
        /**
         * PromptConfigurationAcknowledgementResponse
         * @description Confirmation payload for a completed prompt configuration action.
         */
        PromptConfigurationAcknowledgementResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /** PromptSessionTypeResponse */
        PromptSessionTypeResponse: {
            /** Body */
            body: string;
            /** Default Agent Prompt Ids */
            default_agent_prompt_ids: string[];
            /** Description */
            description: string;
            /** Include Unchanged Research Material Context In Prompt */
            include_unchanged_research_material_context_in_prompt: boolean;
            /** Inputs */
            inputs: components["schemas"]["SessionInputDefinition"][];
            /** Is Shipped */
            is_shipped: boolean;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /**
             * Origin
             * @enum {string}
             */
            origin: "shipped_default" | "shipped_modified" | "custom";
        };
        /**
         * PromptSource
         * @description One ordered source block used to assemble a prompt preview.
         */
        PromptSource: {
            /** Content */
            content: string;
            /**
             * Key
             * @enum {string}
             */
            key: "context" | "globals" | "role" | "task" | "output_format";
        };
        /**
         * ProviderProvenanceResponse
         * @description Safe role and provider selection frozen for one historical round.
         */
        ProviderProvenanceResponse: {
            /** Api Host */
            api_host: string;
            /** Client Id */
            client_id: string | null;
            /** Host Configuration Id */
            host_configuration_id: string | null;
            /** Host Label */
            host_label: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "perspective" | "synthesis";
            /** Model Id */
            model_id: string;
            /** Perspective Number */
            perspective_number: number | null;
            /** Prompt Id */
            prompt_id: string;
            /** Prompt Label */
            prompt_label: string;
            /** Temperature */
            temperature: number | null;
        };
        /** ProviderRebindRequest */
        ProviderRebindRequest: {
            /** Configuration Id */
            configuration_id: string;
            /** Model Id */
            model_id: string;
        };
        /**
         * QuickActionCreateRequest
         * @description New actions append to the configured installation-wide order.
         */
        QuickActionCreateRequest: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Prompt */
            prompt: string;
        };
        /** QuickActionDeleteResponse */
        QuickActionDeleteResponse: {
            /** Deleted */
            deleted: string;
        };
        /**
         * QuickActionInfo
         * @description Editor response including immutable shipped/default provenance.
         */
        QuickActionInfo: {
            /** Id */
            id: string;
            /** Is Shipped */
            is_shipped: boolean;
            /** Label */
            label: string;
            /** Origin */
            origin: string;
            /** Prompt */
            prompt: string;
        };
        /**
         * QuickActionListResponse
         * @description Current actions plus whether restoring defaults would change them.
         */
        QuickActionListResponse: {
            /** Actions */
            actions: components["schemas"]["QuickActionInfo"][];
            /** Can Restore Defaults */
            can_restore_defaults: boolean;
        };
        /** QuickActionRestoreResponse */
        QuickActionRestoreResponse: {
            /** Restored */
            restored: string[];
        };
        /** QuickActionUpdateRequest */
        QuickActionUpdateRequest: {
            /** Label */
            label?: string | null;
            /** Prompt */
            prompt?: string | null;
        };
        /** RenameSessionRequest */
        RenameSessionRequest: {
            /** Title */
            title: string;
        };
        /**
         * RestoreDefaultsResponse
         * @description Identifiers restored from the immutable shipped prompt baseline.
         */
        RestoreDefaultsResponse: {
            /** Restored */
            restored: string[];
        };
        /**
         * RevealGlobalsDirectoryResponse
         * @description Success payload for opening the active global-prompts directory.
         */
        RevealGlobalsDirectoryResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /**
         * RevealLocalAIModelsDirectoryResponse
         * @description Success payload for opening the local AI models directory.
         */
        RevealLocalAIModelsDirectoryResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /** RevealRoleResponse */
        RevealRoleResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /**
         * RevealRolesDirectoryResponse
         * @description Success payload for opening the active roles directory.
         */
        RevealRolesDirectoryResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /** RevealSessionResponse */
        RevealSessionResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /**
         * RevealSessionTypesDirectoryResponse
         * @description Success payload for opening the active session-types directory.
         */
        RevealSessionTypesDirectoryResponse: {
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /**
         * RoleCreateRequest
         * @description Body for POST /api/prompts/roles.
         */
        RoleCreateRequest: {
            /**
             * Description
             * @description Non-prompt setup description
             */
            description?: string | null;
            /**
             * Id
             * @description Unique role identifier
             */
            id: string;
            /**
             * Label
             * @description Human-readable label
             */
            label: string;
            /**
             * Output Format
             * @description Output format instruction
             */
            output_format?: string | null;
            /**
             * Role
             * @description Role instruction text
             */
            role: string;
            /**
             * Task
             * @description Task instruction text
             */
            task?: string | null;
        };
        /** RoleResponse */
        RoleResponse: {
            /** Description */
            description?: string | null;
            /** Editable */
            editable: boolean;
            /** Id */
            id: string;
            /** Is Shipped */
            is_shipped: boolean;
            /** Label */
            label: string;
            /**
             * Origin
             * @enum {string}
             */
            origin: "shipped_default" | "shipped_modified" | "custom";
            /** Output Format */
            output_format: string;
            /** Role */
            role: string;
            /** Task */
            task: string;
        };
        /**
         * RoleUpdateRequest
         * @description Body for PUT /api/prompts/roles/{role_id}. All fields optional.
         */
        RoleUpdateRequest: {
            /**
             * Description
             * @description New non-prompt setup description
             */
            description?: string | null;
            /**
             * Label
             * @description New label
             */
            label?: string | null;
            /**
             * Output Format
             * @description New output format
             */
            output_format?: string | null;
            /**
             * Role
             * @description New role text
             */
            role?: string | null;
            /**
             * Task
             * @description New task text
             */
            task?: string | null;
        };
        /** RoundProviderProvenanceResponse */
        RoundProviderProvenanceResponse: {
            /** Providers */
            providers: components["schemas"]["ProviderProvenanceResponse"][];
            /** Round Number */
            round_number: number;
        };
        /**
         * SavedHostTestRequest
         * @description Edit-test details tied to the saved host expected at the route index.
         */
        SavedHostTestRequest: {
            /**
             * Api Key
             * @description Optional API key
             */
            api_key?: string | null;
            /**
             * Configuration Id
             * @description Expected saved host identity
             */
            configuration_id: string;
            /**
             * Url
             * @description Host URL (http:// or https://)
             */
            url: string;
        };
        /**
         * SavedSessionHostDependency
         * @description Path-free saved-session identity retained after host deletion.
         */
        SavedSessionHostDependency: {
            /** File Id */
            file_id: string;
            /** Title */
            title: string;
        };
        /**
         * SessionInputDefinition
         * @description One semantic setup field with session-specific UI metadata.
         *
         *     ``prompt_heading`` is intentionally not localized: it becomes a stable
         *     heading in the model context, whereas labels and hints are UI metadata.
         */
        SessionInputDefinition: {
            /** Default Text */
            default_text?: string | null;
            /** Hint */
            hint?: string | null;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Prompt Heading */
            prompt_heading: string;
            /**
             * Required
             * @default false
             */
            required: boolean;
        };
        /**
         * SessionInputValuesModel
         * @description The immutable semantic values submitted for every session type.
         */
        SessionInputValuesModel: {
            /** Additional Instructions */
            additional_instructions: string;
            /** Main Input */
            main_input: string;
            /** Research Material Context */
            research_material_context: string;
        };
        /**
         * SessionSummaryModel
         * @description Public, path-free metadata for a stored discussion.
         */
        SessionSummaryModel: {
            /** Created */
            created: string;
            /** File Id */
            file_id: string;
            /** Is Favorite */
            is_favorite: boolean;
            /** Is Open */
            is_open: boolean;
            /** Round Count */
            round_count: number;
            /** Session Type */
            session_type: string;
            /** Title */
            title: string;
            /** Updated */
            updated: string;
        };
        /**
         * SessionTypeCreateRequest
         * @description Body for ``POST /api/prompts/session-types``.
         *
         *     Mirrors :class:`SessionTypeDefinition` so Pydantic enforces the
         *     repository's invariants (key format, non-empty fields, valid agent
         *     IDs) and returns 422 on bad input.
         */
        SessionTypeCreateRequest: {
            /** Body */
            body: string;
            /** Default Agent Prompt Ids */
            default_agent_prompt_ids?: string[];
            /** Description */
            description: string;
            /**
             * Include Unchanged Research Material Context In Prompt
             * @default false
             */
            include_unchanged_research_material_context_in_prompt: boolean;
            /** Inputs */
            inputs?: components["schemas"]["SessionInputDefinition"][];
            /** Key */
            key: string;
            /** Label */
            label: string;
        };
        /**
         * SessionTypeUpdateRequest
         * @description Body for ``PUT /api/prompts/session-types/{key}``.
         *
         *     The ``key`` from the URL is authoritative; a ``key`` field in the
         *     body is intentionally ignored (``extra="ignore"``) so clients cannot
         *     perform a rename by smuggling it through. Every other field is
         *     optional and falls back to the existing definition's value when
         *     absent.
         */
        SessionTypeUpdateRequest: {
            /** Body */
            body?: string | null;
            /** Default Agent Prompt Ids */
            default_agent_prompt_ids?: string[] | null;
            /** Description */
            description?: string | null;
            /** Include Unchanged Research Material Context In Prompt */
            include_unchanged_research_material_context_in_prompt?: boolean | null;
            /** Inputs */
            inputs?: components["schemas"]["SessionInputDefinition"][] | null;
            /** Label */
            label?: string | null;
        };
        /** SetSessionFavoriteRequest */
        SetSessionFavoriteRequest: {
            /** Is Favorite */
            is_favorite: boolean;
        };
        /** StartDiscussionRequest */
        StartDiscussionRequest: {
            /** Agents */
            agents: components["schemas"]["AgentConfigModel"][];
            /**
             * Material
             * @default
             */
            material: string;
            material_context: components["schemas"]["MaterialContextModel"];
            /**
             * Sequential Mode
             * @default false
             */
            sequential_mode: boolean;
            synthesis: components["schemas"]["SynthesisConfigModel"];
            /**
             * Title
             * @default
             */
            title: string;
        };
        /**
         * SynthesisConfigModel
         * @description Safe settings for the dedicated non-participant synthesis phase.
         */
        SynthesisConfigModel: {
            /** Api Host */
            api_host: string | null;
            /** Enabled */
            enabled: boolean;
            /** Host Configuration Id */
            host_configuration_id?: string | null;
            /** Host Label */
            host_label?: string | null;
            /** Llm Id */
            llm_id: string | null;
            /** Temperature */
            temperature: number | null;
        };
        /** TemplateInfo */
        TemplateInfo: {
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** TestHostResponse */
        TestHostResponse: {
            /** Code */
            code: string;
            /** Message */
            message: string;
            /** Models */
            models: string[];
            /** Ok */
            ok: boolean;
        };
        /** UIPreferencesResponse */
        UIPreferencesResponse: {
            /**
             * Ai Source
             * @enum {string}
             */
            ai_source: "integrated" | "external";
            /**
             * Appearance
             * @enum {string}
             */
            appearance: "system" | "light" | "dark";
            /** Last Active Discussion Id */
            last_active_discussion_id: string | null;
            /** Local Ai Context Default Tokens */
            local_ai_context_default_tokens: number;
            /** Local Ai Context Tokens */
            local_ai_context_tokens: number;
            /** Local Ai Mtp Enabled */
            local_ai_mtp_enabled: boolean;
            /** Notification Permission Auto Attempted */
            notification_permission_auto_attempted: boolean;
            /** Notifications Enabled */
            notifications_enabled: boolean;
            /** Prevent Sleep While Generating */
            prevent_sleep_while_generating: boolean;
            /**
             * Ui Locale
             * @enum {string}
             */
            ui_locale: "de" | "en";
        };
        /** UIPreferencesUpdateRequest */
        UIPreferencesUpdateRequest: {
            /** Ai Source */
            ai_source?: ("integrated" | "external") | null;
            /** Appearance */
            appearance?: ("system" | "light" | "dark") | null;
            /** Last Active Discussion Id */
            last_active_discussion_id?: string | null;
            /** Local Ai Context Model Id */
            local_ai_context_model_id?: ("gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b") | null;
            /** Local Ai Context Tokens */
            local_ai_context_tokens?: number | null;
            /** Local Ai Mtp Enabled */
            local_ai_mtp_enabled?: boolean | null;
            /** Notification Permission Auto Attempted */
            notification_permission_auto_attempted?: true | null;
            /** Notifications Enabled */
            notifications_enabled?: boolean | null;
            /** Prevent Sleep While Generating */
            prevent_sleep_while_generating?: boolean | null;
            /** Ui Locale */
            ui_locale?: ("de" | "en") | null;
        };
        /**
         * UpdateDiscussionAgentsRequest
         * @description Strict roster update contract.
         */
        UpdateDiscussionAgentsRequest: {
            /** Agents */
            agents: components["schemas"]["AgentConfigModel"][];
        };
        /** UpdateDiscussionAgentsResponse */
        UpdateDiscussionAgentsResponse: {
            /** Agent Count */
            agent_count: number;
        };
        /**
         * UpdateNextRoundConfigurationRequest
         * @description Atomic full replacement of every editable between-round setting.
         */
        UpdateNextRoundConfigurationRequest: {
            /** Agents */
            agents: components["schemas"]["NextRoundAgentConfigModel"][];
            /** File Id */
            file_id: string;
            synthesis: components["schemas"]["NextRoundSynthesisConfigModel"];
        };
        /** UpdateNextRoundConfigurationResponse */
        UpdateNextRoundConfigurationResponse: {
            /** Agent Count */
            agent_count: number;
        };
        /**
         * UpdateSynthesisRequest
         * @description Strict replacement contract for between-round synthesis settings.
         */
        UpdateSynthesisRequest: {
            /** File Id */
            file_id: string;
            synthesis: components["schemas"]["SynthesisConfigModel"];
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    application_activity_api_application_activity_get: {
        parameters: {
            query?: {
                after?: number;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationActivityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    application_preferences_api_application_preferences_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UIPreferencesResponse"];
                };
            };
        };
    };
    update_application_preferences_api_application_preferences_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UIPreferencesUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UIPreferencesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    quit_application_api_application_quit_post: {
        parameters: {
            query?: never;
            header?: {
                "x-aqa-action"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    application_status_api_application_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: boolean | string | null;
                    };
                };
            };
        };
    };
    get_default_material_api_defaults_material_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DefaultMaterialResponse"];
                };
            };
        };
    };
    update_discussion_agents_api_discussions_agents_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateDiscussionAgentsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateDiscussionAgentsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_discussion_generation_api_discussions_cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CancelDiscussionResponse"];
                };
            };
        };
    };
    estimate_discussion_context_api_discussions_context_estimate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContextEstimateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContextEstimateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    continue_discussion_api_discussions_continue_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContinueDiscussionRequest"];
            };
        };
        responses: {
            /** @description A sequence of JSON payloads encoded as text/event-stream. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiscussionStreamEventResponse"];
                    "text/event-stream": components["schemas"]["DiscussionStreamEventResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_default_agents_api_discussions_defaults_agents_get: {
        parameters: {
            query?: {
                session_type?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": string[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_discussion_api_discussions_export_get: {
        parameters: {
            query?: {
                locale?: "de" | "en";
                download_filename?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_message_context_inclusion_api_discussions_messages__message_id__context_inclusion_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                message_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MessageContextInclusionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MessageContextInclusionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_message_note_api_discussions_messages__message_id__note_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                message_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_message_note_api_discussions_messages__message_id__note_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                message_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_next_round_configuration_api_discussions_next_round_configuration_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateNextRoundConfigurationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateNextRoundConfigurationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_discussion_perspectives_api_discussions_perspectives_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PerspectiveResponse"][];
                };
            };
        };
    };
    get_provider_provenance_api_discussions_provider_provenance_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoundProviderProvenanceResponse"][];
                };
            };
        };
    };
    reset_discussion_api_discussions_reset_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_discussion_session_types_api_discussions_session_types_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiscussionSessionTypeResponse"][];
                };
            };
        };
    };
    start_discussion_api_discussions_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StartDiscussionRequest"];
            };
        };
        responses: {
            /** @description A sequence of JSON payloads encoded as text/event-stream. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiscussionStreamEventResponse"];
                    "text/event-stream": components["schemas"]["DiscussionStreamEventResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_discussion_state_api_discussions_state_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiscussionStateResponse"];
                };
            };
        };
    };
    update_discussion_synthesis_api_discussions_synthesis_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateSynthesisRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    healthcheck_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_hosts_api_hosts_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostInfoResponse"][];
                };
            };
        };
    };
    create_host_api_hosts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HostCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostInfoResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_host_api_hosts_delete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HostDeleteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostDeleteResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_host_deletion_api_hosts_delete_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HostDeletePreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostDeletePreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_draft_host_api_hosts_test_connection_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DraftHostTestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestHostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_host_api_hosts__index__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                index: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HostUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostInfoResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_host_models_api_hosts__index__models_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                index: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostModelsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reset_managed_local_ai_host_api_hosts__index__reset_managed_local_ai_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                index: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_host_api_hosts__index__test_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                index: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SavedHostTestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestHostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_local_ai_diagnostics_api_local_ai_diagnostics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIDiagnosticsResponse"];
                };
            };
        };
    };
    finalize_local_ai_model_import_api_local_ai_imports_finalize_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIImportFinalizeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    abort_local_ai_model_import_api_local_ai_imports__import_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_local_ai_import_part_api_local_ai_imports__import_id___artifact__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
                artifact: "main" | "draft";
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    install_local_ai_api_local_ai_install_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIInstallRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_local_ai_install_api_local_ai_install_cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAICancelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_local_ai_model_api_local_ai_models_delete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIDeleteModelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_local_ai_model_from_directory_api_local_ai_models_import_from_directory_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIBackgroundImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DetectedModelImportJobResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_local_ai_models_directory_api_local_ai_models_reveal_directory_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevealLocalAIModelsDirectoryResponse"];
                };
            };
        };
    };
    delete_local_ai_model_by_id_api_local_ai_models__model_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    begin_local_ai_model_import_api_local_ai_models__model_id__import_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportStartResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    install_local_ai_model_api_local_ai_models__model_id__install_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_id: "gemma-4-e2b" | "gemma-4-e4b" | "gemma-4-12b";
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIInstallOptions"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_local_ai_preferred_model_api_local_ai_preferred_model_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIPreferredModelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_local_ai_runtime_api_local_ai_runtime_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
        };
    };
    update_local_ai_runtime_api_local_ai_runtime_update_post: {
        parameters: {
            query?: {
                cpu_fallback?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_local_ai_api_local_ai_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalAIStartRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_local_ai_status_api_local_ai_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
        };
    };
    stop_local_ai_api_local_ai_stop_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalAIStatusResponse"];
                };
            };
        };
    };
    estimate_material_tokens_api_material_token_estimate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaterialTokenEstimateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaterialTokenEstimateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_line_numbers_api_material_with_line_numbers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaterialLineNumberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaterialLineNumberResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_preview_templates_api_preview_templates_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateInfo"][];
                };
            };
        };
    };
    render_preview_api_preview__template_id__get: {
        parameters: {
            query?: {
                multi_agent?: boolean;
                session_type?: string;
                scenario?: string;
            };
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PreviewResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_prompt_globals_api_prompts_globals_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GlobalBlockResponse"][];
                };
            };
        };
    };
    restore_default_globals_api_prompts_globals_restore_defaults_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreDefaultsResponse"];
                };
            };
        };
    };
    reveal_globals_directory_endpoint_api_prompts_globals_reveal_directory_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevealGlobalsDirectoryResponse"];
                };
            };
        };
    };
    update_prompt_global_api_prompts_globals__global_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                global_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GlobalUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GlobalBlockResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_global_api_prompts_globals__global_id__restore_default_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                global_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreDefaultsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_roles_api_prompts_roles_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoleResponse"][];
                };
            };
        };
    };
    create_role_api_prompts_roles_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RoleCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoleResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_roles_api_prompts_roles_restore_defaults_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreDefaultsResponse"];
                };
            };
        };
    };
    reveal_roles_directory_endpoint_api_prompts_roles_reveal_directory_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevealRolesDirectoryResponse"];
                };
            };
        };
    };
    get_role_api_prompts_roles__role_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                role_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoleResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_role_api_prompts_roles__role_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                role_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RoleUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoleResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_role_api_prompts_roles__role_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                role_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptConfigurationAcknowledgementResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_role_api_prompts_roles__role_id__restore_default_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                role_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreDefaultsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_role_endpoint_api_prompts_roles__role_id__reveal_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                role_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevealRoleResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_prompt_session_types_api_prompts_session_types_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptSessionTypeResponse"][];
                };
            };
        };
    };
    create_prompt_session_type_api_prompts_session_types_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SessionTypeCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptSessionTypeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_session_types_api_prompts_session_types_restore_defaults_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreDefaultsResponse"];
                };
            };
        };
    };
    reveal_session_types_directory_endpoint_api_prompts_session_types_reveal_directory_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevealSessionTypesDirectoryResponse"];
                };
            };
        };
    };
    update_prompt_session_type_api_prompts_session_types__key__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SessionTypeUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptSessionTypeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_prompt_session_type_api_prompts_session_types__key__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeletePromptConfigurationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_session_type_api_prompts_session_types__key__restore_default_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreDefaultsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_quick_actions_api_quick_actions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuickActionListResponse"];
                };
            };
        };
    };
    create_quick_action_api_quick_actions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuickActionCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuickActionInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_quick_actions_api_quick_actions_restore_defaults_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuickActionRestoreResponse"];
                };
            };
        };
    };
    update_quick_action_api_quick_actions__action_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                action_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuickActionUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuickActionInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_quick_action_api_quick_actions__action_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                action_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuickActionDeleteResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_default_quick_action_api_quick_actions__action_id__restore_default_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                action_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuickActionRestoreResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sessions_api_sessions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSummaryModel"][];
                };
            };
        };
    };
    bulk_delete_sessions_api_sessions_bulk_delete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BulkDeleteSessionsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkDeleteSessionsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_session_api_sessions__file_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                file_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteSessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rename_session_api_sessions__file_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                file_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RenameSessionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSummaryModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_session_favorite_api_sessions__file_id__favorite_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                file_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetSessionFavoriteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSummaryModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    open_session_api_sessions__file_id__open_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                file_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OpenSessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_session_api_sessions__file_id__reveal_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                file_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevealSessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}

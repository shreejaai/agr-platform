export type CopilotRole = 'user' | 'assistant';

export type CopilotActionType =
  | 'create_policy' | 'list_policies' | 'delete_policy'
  | 'register_agent' | 'list_agents'
  | 'create_webhook' | 'list_webhooks'
  | 'explain' | 'sample' | 'general' | 'error'
  | 'confirm_pending' | 'confirmed' | 'cancelled';

export interface CopilotMessage {
  role: CopilotRole;
  content: string;
}

export interface CopilotPreview {
  resource_type: 'policy' | 'agent' | 'webhook';
  data: Record<string, unknown>;
  cedar_rule?: string;
  confirmation_prompt: string;
}

export interface CopilotRequest {
  message: string;
  conversation_id: string | null;
  auto_confirm?: boolean;
  confirm_preview?: CopilotPreview;
}

export interface CopilotResponse {
  message: string;
  action_type: CopilotActionType;
  conversation_id: string;
  preview?: CopilotPreview;
  created_resource?: Record<string, unknown>;
  suggestions?: string[];
}

export interface ChatEntry {
  role: CopilotRole;
  content: string;
  action_type?: CopilotActionType;
  preview?: CopilotPreview;
  created_resource?: Record<string, unknown>;
  suggestions?: string[];
  timestamp: Date;
}

export interface ConversationSummary {
  id: string;
  title: string;
  message_count: number;
  updated_at: string;
}

export interface ConversationMessage {
  id: string;
  role: CopilotRole;
  content: string;
  action_type?: string;
  metadata?: {
    preview?: CopilotPreview;
    created_resource?: Record<string, unknown>;
    suggestions?: string[];
  };
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
}

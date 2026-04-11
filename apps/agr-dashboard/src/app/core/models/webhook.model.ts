export type WebhookEvent = 'approval.approved' | 'approval.rejected';

export interface Webhook {
  id: string;
  org_id: string;
  url: string;
  secret: string;
  events: WebhookEvent[];
  active: boolean;
  rotating_secret_expires_at: string | null;
  url_warning: string | null;
  created_at: string;
}

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  org_id: string;
  event: string;
  payload: Record<string, unknown>;
  status: 'pending' | 'success' | 'failed';
  http_status: number | null;
  attempts: number;
  last_error: string | null;
  created_at: string;
}

export interface WebhookCreate {
  url: string;
  events: WebhookEvent[];
}

export interface WebhookUpdate {
  url?: string;
  events?: WebhookEvent[];
  active?: boolean;
}

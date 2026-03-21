export type WebhookEvent = 'approval.approved' | 'approval.rejected';

export interface Webhook {
  id: string;
  org_id: string;
  url: string;
  secret: string;
  events: WebhookEvent[];
  active: boolean;
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

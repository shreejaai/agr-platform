-- 008_down.sql — rollback for 008_webhook_deliveries.sql
DROP TABLE IF EXISTS webhook_deliveries CASCADE;

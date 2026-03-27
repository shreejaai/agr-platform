export type ComplianceSeverityLevel = 'low' | 'medium' | 'high' | 'critical';

export interface ComplianceFinding {
  plugin: string;
  standard: string;
  rule_id: string;
  severity: string;
  message: string;
  passed: boolean;
  remediation_steps?: string[];
  severity_level?: ComplianceSeverityLevel;
  compliance_score?: number;
}

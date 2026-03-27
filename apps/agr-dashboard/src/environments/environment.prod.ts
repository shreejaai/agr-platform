export const environment = {
  production: true,
  // Injected at build time via CI using Angular fileReplacements or env substitution.
  // CI sets this from the CLERK_PUBLISHABLE_KEY secret — see .github/workflows/ci.yml.
  // Placeholder here is intentional; a build with this literal value will fail auth.
  clerkPublishableKey: 'pk_live_REPLACE_AT_BUILD_TIME',
  apiBase: '/v1',
};

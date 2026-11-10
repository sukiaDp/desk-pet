export type Enabled = boolean

declare module 'claude-code' {
  interface PluginState {
    'desk-pet': { enabled: Enabled }
  }
}

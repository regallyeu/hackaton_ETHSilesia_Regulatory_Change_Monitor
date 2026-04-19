import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import plCommon from './locales/pl/common.json'
import plAlerts from './locales/pl/alerts.json'
import plIsap from './locales/pl/isap.json'
import plContracts from './locales/pl/contracts.json'
import plDocuments from './locales/pl/documents.json'
import plCompliance from './locales/pl/compliance.json'

import enCommon from './locales/en/common.json'
import enAlerts from './locales/en/alerts.json'
import enIsap from './locales/en/isap.json'
import enContracts from './locales/en/contracts.json'
import enDocuments from './locales/en/documents.json'
import enCompliance from './locales/en/compliance.json'

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      pl: {
        common: plCommon,
        alerts: plAlerts,
        isap: plIsap,
        contracts: plContracts,
        documents: plDocuments,
        compliance: plCompliance,
      },
      en: {
        common: enCommon,
        alerts: enAlerts,
        isap: enIsap,
        contracts: enContracts,
        documents: enDocuments,
        compliance: enCompliance,
      },
    },
    defaultNS: 'common',
    fallbackLng: 'pl',
    supportedLngs: ['pl', 'en'],
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'i18n_lang',
    },
    interpolation: {
      escapeValue: false,
    },
  })

export default i18n

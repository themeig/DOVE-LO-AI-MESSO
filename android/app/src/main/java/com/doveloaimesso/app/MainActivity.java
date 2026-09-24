package com.doveloaimesso.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.View;
import android.net.http.SslError;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AlertDialog;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import android.app.ProgressDialog;
import android.provider.Settings;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Executors;

public class MainActivity extends AppCompatActivity {

    private static final String PREFS_NAME = "DoveLoAIMessoPrefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String DEFAULT_EMULATOR_URL = "http://10.0.2.2:8000";
    private static final String DEFAULT_WIFI_URL = "http://192.168.178.73:8000";
    private static final String GITHUB_VERSION_URL = "https://raw.githubusercontent.com/themeig/DOVE-LO-AI-MESSO/main/android-release/version.json";
    private static final int PERMISSION_REQUEST_CODE = 1001;

    private WebView webView;
    private SwipeRefreshLayout swipeRefresh;
    private ProgressBar progressBar;
    private LinearLayout errorLayout;
    private EditText etServerUrl;
    private Button btnRetry;
    private Button btnUseWifiIp;
    private TextView tvErrorDetails;

    private ValueCallback<Uri[]> mFilePathCallback;
    private ActivityResultLauncher<Intent> fileChooserLauncher;
    private Uri mCameraPhotoUri;
    private File mCameraPhotoFile;
    private File pendingInstallApkFile = null;
    private String currentServerUrl;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webView);
        swipeRefresh = findViewById(R.id.swipeRefresh);
        progressBar = findViewById(R.id.progressBar);
        errorLayout = findViewById(R.id.errorLayout);
        etServerUrl = findViewById(R.id.etServerUrl);
        btnRetry = findViewById(R.id.btnRetry);
        btnUseWifiIp = findViewById(R.id.btnUseWifiIp);
        tvErrorDetails = findViewById(R.id.tvErrorDetails);

        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        currentServerUrl = prefs.getString(KEY_SERVER_URL, DEFAULT_EMULATOR_URL);
        etServerUrl.setText(currentServerUrl);

        setupFileChooserLauncher();
        setupWebView();
        setupListeners();
        checkAndRequestAppPermissions();

        loadUrl(currentServerUrl);
        checkForUpdates();

        // Gestione tasto indietro hardware nativo
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (webView != null && webView.canGoBack()) {
                    webView.goBack();
                } else {
                    finish();
                }
            }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (pendingInstallApkFile != null && pendingInstallApkFile.exists() && pendingInstallApkFile.length() > 0) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || getPackageManager().canRequestPackageInstalls()) {
                File toInstall = pendingInstallApkFile;
                pendingInstallApkFile = null;
                installDownloadedApk(toInstall);
            }
        }
    }

    private void setupListeners() {
        swipeRefresh.setColorSchemeResources(R.color.primary, R.color.accent);
        swipeRefresh.setOnRefreshListener(() -> {
            if (webView != null) {
                webView.clearCache(true);
                webView.reload();
            } else {
                swipeRefresh.setRefreshing(false);
            }
        });

        btnRetry.setOnClickListener(v -> {
            String url = etServerUrl.getText().toString().trim();
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                url = "http://" + url;
            }
            saveServerUrl(url);
            errorLayout.setVisibility(View.GONE);
            loadUrl(url);
        });

        btnUseWifiIp.setOnClickListener(v -> {
            String subnet = getSuggestedSubnetUrl();
            etServerUrl.setText(subnet);
            if (subnet.contains(":8000")) {
                int colonIdx = subnet.lastIndexOf(':');
                etServerUrl.setSelection(colonIdx);
            } else {
                etServerUrl.setSelection(subnet.length());
            }
            Toast.makeText(this, "Completa l'IP del tuo computer (es. da 'ipconfig' sul PC)", Toast.LENGTH_LONG).show();
        });
    }

    private String getSuggestedSubnetUrl() {
        try {
            java.util.Enumeration<java.net.NetworkInterface> interfaces = java.net.NetworkInterface.getNetworkInterfaces();
            while (interfaces.hasMoreElements()) {
                java.net.NetworkInterface iface = interfaces.nextElement();
                java.util.Enumeration<java.net.InetAddress> addrs = iface.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    java.net.InetAddress addr = addrs.nextElement();
                    if (!addr.isLoopbackAddress() && addr instanceof java.net.Inet4Address) {
                        String ip = addr.getHostAddress();
                        if (ip != null && (ip.startsWith("192.168.") || ip.startsWith("10.") || ip.startsWith("172."))) {
                            int lastDot = ip.lastIndexOf('.');
                            return "http://" + ip.substring(0, lastDot + 1) + ":8000";
                        }
                    }
                }
            }
        } catch (Exception ignored) {}
        return "http://192.168.1.:8000";
    }

    private void saveServerUrl(String url) {
        currentServerUrl = url;
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(KEY_SERVER_URL, url).apply();
    }

    private void loadUrl(String url) {
        currentServerUrl = url;
        progressBar.setVisibility(View.VISIBLE);
        webView.loadUrl(url);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);

        // User Agent mobile moderno
        String defaultUA = settings.getUserAgentString();
        settings.setUserAgentString(defaultUA + " DoveLoAIMessoApp/2.5.7");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                progressBar.setVisibility(View.VISIBLE);
                errorLayout.setVisibility(View.GONE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progressBar.setVisibility(View.GONE);
                swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                // Consenti certificati locali e autofirmati per sviluppo/LAN
                handler.proceed();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    progressBar.setVisibility(View.GONE);
                    swipeRefresh.setRefreshing(false);
                    errorLayout.setVisibility(View.VISIBLE);
                    tvErrorDetails.setText("Errore di connessione a: " + currentServerUrl + "\n(" + error.getDescription() + ")");
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme();
                if (scheme != null && !scheme.equals("http") && !scheme.equals("https")) {
                    try {
                        Intent intent = new Intent(Intent.ACTION_VIEW, uri);
                        startActivity(intent);
                        return true;
                    } catch (Exception e) {
                        return false;
                    }
                }
                return false;
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                // Concessione automatica dei permessi web per cattura audio e video (fotocamera / microfono)
                runOnUiThread(() -> {
                    String[] resources = request.getResources();
                    request.grant(resources);
                });
            }

            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback, FileChooserParams fileChooserParams) {
                if (mFilePathCallback != null) {
                    mFilePathCallback.onReceiveValue(null);
                }
                mFilePathCallback = filePathCallback;

                boolean isCapture = fileChooserParams != null && fileChooserParams.isCaptureEnabled();
                Intent takePictureIntent = null;
                mCameraPhotoUri = null;
                mCameraPhotoFile = null;

                try {
                    Intent cameraIntent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    File photoFile = createImageFile();
                    if (photoFile != null) {
                        mCameraPhotoFile = photoFile;
                        mCameraPhotoUri = FileProvider.getUriForFile(
                                MainActivity.this,
                                getPackageName() + ".fileprovider",
                                photoFile
                        );
                        cameraIntent.putExtra(MediaStore.EXTRA_OUTPUT, mCameraPhotoUri);
                        cameraIntent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        takePictureIntent = cameraIntent;
                    }
                } catch (Exception ex) {
                    mCameraPhotoUri = null;
                    mCameraPhotoFile = null;
                }

                // Se l'HTML ha espressamente richiesto 'capture' (es. pulsante Fotocamera con capture="environment")
                // apri DIRETTAMENTE l'app Fotocamera nativa senza passare per la gestione file.
                if (isCapture && takePictureIntent != null) {
                    try {
                        fileChooserLauncher.launch(takePictureIntent);
                        return true;
                    } catch (Exception ignored) {}
                }

                // Altrimenti (es. graffetta allegati generici), apri selettore file con opzione fotocamera inclusa
                try {
                    Intent contentSelectionIntent = fileChooserParams != null ? fileChooserParams.createIntent() : new Intent(Intent.ACTION_GET_CONTENT);
                    Intent chooserIntent = new Intent(Intent.ACTION_CHOOSER);
                    chooserIntent.putExtra(Intent.EXTRA_INTENT, contentSelectionIntent);
                    chooserIntent.putExtra(Intent.EXTRA_TITLE, "Seleziona file o scatta foto");
                    if (takePictureIntent != null) {
                        chooserIntent.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{takePictureIntent});
                    }
                    fileChooserLauncher.launch(chooserIntent);
                    return true;
                } catch (Exception e) {
                    // Fallback a selettore generico
                    Intent fallback = new Intent(Intent.ACTION_GET_CONTENT);
                    fallback.addCategory(Intent.CATEGORY_OPENABLE);
                    fallback.setType("*/*");
                    fileChooserLauncher.launch(Intent.createChooser(fallback, "Seleziona file o foto"));
                    return true;
                }
            }
        });
    }

    private File createImageFile() {
        try {
            String timeStamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(new Date());
            File storageDir = getExternalFilesDir(android.os.Environment.DIRECTORY_PICTURES);
            if (storageDir == null) {
                storageDir = getCacheDir();
            }
            if (!storageDir.exists()) {
                storageDir.mkdirs();
            }
            return File.createTempFile("JPEG_" + timeStamp + "_", ".jpg", storageDir);
        } catch (Exception e) {
            return null;
        }
    }

    private void setupFileChooserLauncher() {
        fileChooserLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (mFilePathCallback == null) return;
                    Uri[] results = null;
                    if (result.getResultCode() == Activity.RESULT_OK) {
                        Intent data = result.getData();
                        if (data != null && (data.getData() != null || data.getClipData() != null)) {
                            if (data.getData() != null) {
                                results = new Uri[]{data.getData()};
                            } else if (data.getClipData() != null) {
                                int count = data.getClipData().getItemCount();
                                results = new Uri[count];
                                for (int i = 0; i < count; i++) {
                                    results[i] = data.getClipData().getItemAt(i).getUri();
                                }
                            }
                        } else if (mCameraPhotoUri != null) {
                            // Immagine scattata direttamente dalla fotocamera nativa
                            results = new Uri[]{mCameraPhotoUri};
                        }
                    } else {
                        // Annullato: ripulisci eventuale file temporaneo vuoto
                        if (mCameraPhotoFile != null && mCameraPhotoFile.exists() && mCameraPhotoFile.length() == 0) {
                            try {
                                mCameraPhotoFile.delete();
                            } catch (Exception ignored) {}
                        }
                    }
                    mFilePathCallback.onReceiveValue(results);
                    mFilePathCallback = null;
                    mCameraPhotoUri = null;
                    mCameraPhotoFile = null;
                }
        );
    }

    private void checkAndRequestAppPermissions() {
        List<String> neededPermissions = new ArrayList<>();
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            neededPermissions.add(Manifest.permission.CAMERA);
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            neededPermissions.add(Manifest.permission.RECORD_AUDIO);
        }

        if (!neededPermissions.isEmpty()) {
            ActivityCompat.requestPermissions(this, neededPermissions.toArray(new String[0]), PERMISSION_REQUEST_CODE);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == PERMISSION_REQUEST_CODE) {
            // I permessi sono stati elaborati
            if (webView != null) {
                webView.reload();
            }
        }
    }

    // =========================================================================
    // SISTEMA AGGIORNAMENTI AUTOMATICI OVER-THE-AIR (OTA) DA GITHUB / LAN
    // =========================================================================

    private void checkForUpdates() {
        Executors.newSingleThreadExecutor().execute(() -> {
            try {
                // Attendi 2.5 secondi per dare priorità al caricamento iniziale della UI
                Thread.sleep(2500);
            } catch (InterruptedException ignored) {}

            JSONObject updateJson = null;

            // 1. Verifica disponibilità aggiornamento da GitHub raw
            try {
                updateJson = fetchJsonFromUrl(GITHUB_VERSION_URL);
            } catch (Exception ignored) {
                updateJson = null;
            }

            // 2. Se GitHub è irraggiungibile (es. offline) e c'è un server locale, prova dal server locale
            if (updateJson == null && currentServerUrl != null && !currentServerUrl.isEmpty()) {
                try {
                    String localUrl = currentServerUrl + (currentServerUrl.endsWith("/") ? "" : "/") + "api/app/version";
                    updateJson = fetchJsonFromUrl(localUrl);
                } catch (Exception ignored) {}
            }

            if (updateJson == null) return;

            try {
                int remoteVersionCode = updateJson.optInt("version_code", 0);
                String remoteVersionName = updateJson.optString("version_name", "");
                String apkUrl = updateJson.optString("apk_url", "");
                String releaseNotes = updateJson.optString("release_notes", "Miglioramenti di stabilità e nuove funzionalità.");

                if (apkUrl.startsWith("/") && currentServerUrl != null) {
                    apkUrl = currentServerUrl + apkUrl;
                }

                long localVersionCode = 0;
                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        localVersionCode = getPackageManager().getPackageInfo(getPackageName(), 0).getLongVersionCode();
                    } else {
                        localVersionCode = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                    }
                } catch (Exception ignored) {}

                if (remoteVersionCode > localVersionCode) {
                    final String finalApkUrl = apkUrl;
                    runOnUiThread(() -> showUpdateDialog(remoteVersionName, releaseNotes, finalApkUrl));
                }
            } catch (Exception ignored) {}
        });
    }

    private JSONObject fetchJsonFromUrl(String urlString) throws Exception {
        URL url = new URL(urlString);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(10000);
        conn.setUseCaches(false);
        conn.setRequestProperty("Accept", "application/json");

        if (conn.getResponseCode() == 200) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()))) {
                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line);
                }
                return new JSONObject(sb.toString());
            }
        }
        return null;
    }

    private void showUpdateDialog(String versionName, String releaseNotes, String apkUrl) {
        if (isFinishing() || isDestroyed()) return;
        new AlertDialog.Builder(this)
                .setTitle("Aggiornamento Disponibile (v" + versionName + ")")
                .setMessage("È disponibile una nuova versione di Dove lo AI messo:\n\n"
                        + releaseNotes
                        + "\n\nVuoi scaricare e installare l'aggiornamento adesso?")
                .setPositiveButton("Aggiorna Ora", (dialog, which) -> downloadAndInstallApk(apkUrl))
                .setNegativeButton("Più tardi", null)
                .setCancelable(true)
                .show();
    }

    @SuppressWarnings("deprecation")
    private void downloadAndInstallApk(String apkUrl) {
        ProgressDialog progressDialog = new ProgressDialog(this);
        progressDialog.setTitle("Download Aggiornamento");
        progressDialog.setMessage("Scaricamento del nuovo APK in corso...");
        progressDialog.setProgressStyle(ProgressDialog.STYLE_HORIZONTAL);
        progressDialog.setMax(100);
        progressDialog.setCancelable(false);
        progressDialog.show();

        Executors.newSingleThreadExecutor().execute(() -> {
            File apkFile = new File(getCacheDir(), "DoveLoAIMesso_update.apk");
            boolean success = false;
            try {
                URL url = new URL(apkUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setConnectTimeout(15000);
                conn.setReadTimeout(60000);
                conn.setInstanceFollowRedirects(true);
                conn.connect();

                int fileLength = conn.getContentLength();
                try (InputStream input = conn.getInputStream();
                     FileOutputStream output = new FileOutputStream(apkFile)) {
                    byte[] data = new byte[8192];
                    long total = 0;
                    int count;
                    while ((count = input.read(data)) != -1) {
                        total += count;
                        if (fileLength > 0) {
                            int progress = (int) (total * 100 / fileLength);
                            runOnUiThread(() -> progressDialog.setProgress(progress));
                        }
                        output.write(data, 0, count);
                    }
                    output.flush();
                    success = true;
                }
            } catch (Exception e) {
                success = false;
            }

            final boolean downloaded = success;
            runOnUiThread(() -> {
                try {
                    if (progressDialog.isShowing()) {
                        progressDialog.dismiss();
                    }
                } catch (Exception ignored) {}

                if (downloaded && apkFile.exists() && apkFile.length() > 0) {
                    installDownloadedApk(apkFile);
                } else {
                    Toast.makeText(MainActivity.this, "Errore durante il download dell'APK da GitHub. Riprova più tardi.", Toast.LENGTH_LONG).show();
                }
            });
        });
    }

    private void installDownloadedApk(File apkFile) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (!getPackageManager().canRequestPackageInstalls()) {
                pendingInstallApkFile = apkFile;
                Toast.makeText(this, "Autorizza Dove lo AI messo all'installazione dell'aggiornamento", Toast.LENGTH_LONG).show();
                Intent manageIntent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName()));
                startActivity(manageIntent);
                return;
            }
        }

        try {
            Uri apkUri = FileProvider.getUriForFile(
                    MainActivity.this,
                    getPackageName() + ".fileprovider",
                    apkFile
            );

            Intent installIntent = new Intent(Intent.ACTION_VIEW);
            installIntent.setDataAndType(apkUri, "application/vnd.android.package-archive");
            installIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            installIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(installIntent);
        } catch (Exception e) {
            Toast.makeText(this, "Errore durante l'apertura dell'installer: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }
}

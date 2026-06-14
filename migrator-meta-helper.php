<?php
/**
 * Plugin Name: Migrator Co — Meta Helper
 * Plugin URI: https://latinodigital.cl
 * Description: Endpoint REST API auxiliar para inyectar meta tags (especialmente Rank Math) durante migraciones SEO. Diseñado para uso temporal en staging.
 * Version: 1.0.0
 * Author: Latino Digital
 * License: MIT
 * Text Domain: migrator-meta-helper
 * 
 * ⚠️ ADVERTENCIA DE SEGURIDAD:
 * Este plugin expone un endpoint que permite escribir metadata de posts.
 * Está diseñado para uso TEMPORAL durante migraciones SEO en staging.
 * DESACTIVAR/DESINSTALAR una vez completada la migración.
 * 
 * USO:
 * POST /wp-json/migrator/v1/update-meta
 * 
 * Headers:
 *   Authorization: Basic [base64 de user:app_password]
 *   Content-Type: application/json
 * 
 * Body JSON:
 * {
 *   "post_id": 30716,
 *   "meta": {
 *     "rank_math_title": "Mi título SEO",
 *     "rank_math_description": "Mi descripción SEO",
 *     "rank_math_canonical_url": "https://ejemplo.cl/url/"
 *   }
 * }
 * 
 * Respuesta exitosa:
 * {
 *   "success": true,
 *   "post_id": 30716,
 *   "updated_keys": ["rank_math_title", "rank_math_description"],
 *   "message": "Meta actualizados correctamente"
 * }
 */

// Prevenir acceso directo
if (!defined('ABSPATH')) {
    exit;
}

// Whitelist de meta keys permitidos (seguridad)
// Solo se pueden escribir meta keys que estén en esta lista
function migrator_get_allowed_meta_keys() {
    return [
        // Rank Math (principal)
        'rank_math_title',
        'rank_math_description',
        'rank_math_canonical_url',
        'rank_math_focus_keyword',
        'rank_math_robots',
        'rank_math_advanced_robots',
        'rank_math_facebook_title',
        'rank_math_facebook_description',
        'rank_math_facebook_image',
        'rank_math_facebook_image_id',
        'rank_math_twitter_title',
        'rank_math_twitter_description',
        'rank_math_twitter_image',
        'rank_math_twitter_image_id',
        'rank_math_twitter_card_type',
        
        // Yoast SEO (por si usan ambos)
        '_yoast_wpseo_title',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_canonical',
        '_yoast_wpseo_focuskw',
        
        // All in One SEO (alternativa)
        '_aioseo_title',
        '_aioseo_description',
        '_aioseo_canonical_url',
    ];
}

// Registrar el endpoint REST
add_action('rest_api_init', function () {
    register_rest_route('migrator/v1', '/update-meta', [
        'methods' => 'POST',
        'callback' => 'migrator_update_meta_handler',
        'permission_callback' => 'migrator_check_permissions',
        'args' => [
            'post_id' => [
                'required' => true,
                'validate_callback' => function ($param) {
                    return is_numeric($param) && intval($param) > 0;
                },
            ],
            'meta' => [
                'required' => true,
                'validate_callback' => function ($param) {
                    return is_array($param) && !empty($param);
                },
            ],
        ],
    ]);
    
    // Endpoint de health-check para verificar que el plugin está activo
    register_rest_route('migrator/v1', '/ping', [
        'methods' => 'GET',
        'callback' => function () {
            return [
                'success' => true,
                'plugin' => 'Migrator Co Meta Helper',
                'version' => '1.0.0',
                'allowed_keys_count' => count(migrator_get_allowed_meta_keys()),
            ];
        },
        'permission_callback' => '__return_true', // Ping público
    ]);
});

/**
 * Verifica que el usuario tenga permisos para editar posts
 */
function migrator_check_permissions() {
    // Solo usuarios con capacidad edit_posts pueden usar este endpoint
    // (administradores, editores)
    if (!current_user_can('edit_posts')) {
        return new WP_Error(
            'rest_forbidden',
            'No tienes permisos para editar posts.',
            ['status' => 403]
        );
    }
    return true;
}

/**
 * Handler principal del endpoint update-meta
 */
function migrator_update_meta_handler(WP_REST_Request $request) {
    $post_id = intval($request->get_param('post_id'));
    $meta = $request->get_param('meta');
    
    // Validar que el post existe
    $post = get_post($post_id);
    if (!$post) {
        return new WP_Error(
            'post_not_found',
            sprintf('No se encontró el post con ID %d', $post_id),
            ['status' => 404]
        );
    }
    
    // Validar que el usuario puede editar ESTE post específico
    if (!current_user_can('edit_post', $post_id)) {
        return new WP_Error(
            'cannot_edit_post',
            sprintf('No tienes permisos para editar el post %d', $post_id),
            ['status' => 403]
        );
    }
    
    // Whitelist de keys permitidas
    $allowed_keys = migrator_get_allowed_meta_keys();
    $updated = [];
    $rejected = [];
    $errors = [];
    
    foreach ($meta as $key => $value) {
        // Sanitizar key
        $key = sanitize_key($key);
        
        // Verificar whitelist
        if (!in_array($key, $allowed_keys, true)) {
            $rejected[] = $key;
            continue;
        }
        
        // Sanitizar value (preservar caracteres válidos como acentos)
        if (is_string($value)) {
            // Para URLs, validar
            if (strpos($key, '_url') !== false || strpos($key, 'canonical') !== false) {
                $value = esc_url_raw($value);
            } else {
                // Para texto, sanitizar pero preservar UTF-8
                $value = wp_strip_all_tags($value);
            }
        } elseif (is_array($value)) {
            $value = array_map('wp_strip_all_tags', $value);
        }
        
        // Update con manejo de errores
        $result = update_post_meta($post_id, $key, $value);
        
        if ($result !== false) {
            $updated[] = $key;
        } else {
            // update_post_meta devuelve false si:
            // 1. El valor es idéntico al existente (no es error)
            // 2. Hubo un error real
            // Verificamos si el valor está guardado
            $stored = get_post_meta($post_id, $key, true);
            if ($stored === $value || $stored == $value) {
                $updated[] = $key; // El valor está guardado, no hubo error
            } else {
                $errors[] = $key;
            }
        }
    }
    
    // Log opcional para debugging (comentado por defecto)
    // error_log(sprintf('[Migrator Meta Helper] post_id=%d updated=%s rejected=%s', 
    //     $post_id, implode(',', $updated), implode(',', $rejected)));
    
    $response = [
        'success' => count($updated) > 0,
        'post_id' => $post_id,
        'post_title' => $post->post_title,
        'updated_keys' => $updated,
        'updated_count' => count($updated),
    ];
    
    if (!empty($rejected)) {
        $response['rejected_keys'] = $rejected;
        $response['rejected_message'] = 'Estos keys no están en el whitelist (por seguridad)';
    }
    
    if (!empty($errors)) {
        $response['error_keys'] = $errors;
    }
    
    if (count($updated) === 0 && count($rejected) > 0) {
        return new WP_Error(
            'no_keys_updated',
            'Ningún meta key permitido fue actualizado',
            ['status' => 400, 'response' => $response]
        );
    }
    
    return rest_ensure_response($response);
}

/**
 * Mensaje en el admin cuando el plugin está activo
 * (Solo aparece en páginas relevantes del admin)
 */
add_action('admin_notices', function () {
    $screen = get_current_screen();
    if ($screen && in_array($screen->id, ['plugins', 'tools_page_migrator-meta-helper'])) {
        echo '<div class="notice notice-info"><p>';
        echo '<strong>Migrator Co Meta Helper:</strong> ';
        echo 'Plugin activo. Endpoint disponible en: <code>POST /wp-json/migrator/v1/update-meta</code>. ';
        echo '⚠️ Recuerda desactivar este plugin después de completar la migración.';
        echo '</p></div>';
    }
});

// Mensaje en la página de plugins
add_filter('plugin_row_meta', function ($links, $file) {
    if (strpos($file, 'migrator-meta-helper') !== false) {
        $links[] = '<strong style="color: #d63638;">⚠️ Plugin temporal — desactivar después de migración</strong>';
    }
    return $links;
}, 10, 2);
